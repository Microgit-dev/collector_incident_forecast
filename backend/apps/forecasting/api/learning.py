"""
API окна «Обучение и обратная связь» (аналитик): правила разметки, очередь меток из решений
диспетчеров, их влияние на модели и настройки дообучения. Все изменения пишутся в журнал действий.
"""

from django.db.models import Count, Q
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import log_action
from apps.core.permissions import require_perm

from .. import feedback
from ..models import FeedbackLabel, FeedbackRule, LearningSettings

REVIEW = require_perm("forecasting.review_feedback")


class FeedbackRuleSerializer(serializers.ModelSerializer):
    labels_total = serializers.IntegerField(read_only=True)
    labels_accepted = serializers.IntegerField(read_only=True)

    class Meta:
        model = FeedbackRule
        fields = (
            "id",
            "code",
            "title",
            "effect",
            "weight",
            "auto_accept",
            "enabled",
            "description",
            "labels_total",
            "labels_accepted",
            "updated_at",
        )
        read_only_fields = ("code", "title", "labels_total", "labels_accepted", "updated_at")


class FeedbackRuleViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = FeedbackRuleSerializer
    permission_classes = [REVIEW]
    pagination_class = None

    def get_queryset(self):
        return FeedbackRule.objects.annotate(
            labels_total=Count("feedbacklabel"),
            labels_accepted=Count(
                "feedbacklabel", filter=Q(feedbacklabel__status=FeedbackLabel.Status.ACCEPTED)
            ),
        ).order_by("effect", "code")

    def perform_update(self, serializer):
        rule = serializer.save()
        log_action(self.request, "feedback.rule", obj=rule, payload=dict(serializer.validated_data))


class FeedbackLabelSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source="channel.name", read_only=True)
    node_name = serializers.CharField(source="channel.node.name", read_only=True)
    rule_title = serializers.CharField(source="rule.title", default=None, read_only=True)
    decided_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    incident_title = serializers.CharField(source="incident.title", default=None, read_only=True)
    model_version = serializers.CharField(source="last_used_model.version", default=None, read_only=True)

    class Meta:
        model = FeedbackLabel
        fields = (
            "id",
            "source",
            "channel",
            "channel_name",
            "node_name",
            "label_date",
            "effect",
            "weight",
            "status",
            "rule",
            "rule_title",
            "decision",
            "incident",
            "incident_title",
            "decided_by",
            "decided_by_name",
            "reviewed_by_name",
            "reviewed_at",
            "review_comment",
            "rows_affected",
            "model_version",
            "created_at",
        )

    @staticmethod
    def _name(user):
        return (user.get_full_name() or user.get_username()) if user else None

    def get_decided_by_name(self, obj):
        return self._name(obj.decided_by)

    def get_reviewed_by_name(self, obj):
        return self._name(obj.reviewed_by)


class BulkReviewSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[FeedbackLabel.Status.ACCEPTED, FeedbackLabel.Status.REJECTED])
    ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    decision = serializers.IntegerField(required=False)
    decided_by = serializers.IntegerField(required=False)
    rule = serializers.IntegerField(required=False)
    source = serializers.ChoiceField(choices=FeedbackLabel.Source.choices, required=False)
    only_status = serializers.ChoiceField(choices=FeedbackLabel.Status.choices, required=False)
    comment = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if not any(attrs.get(k) for k in ("ids", "decision", "decided_by", "rule", "source")):
            raise serializers.ValidationError("Укажите метки: ids, решение, диспетчера или правило")
        return attrs


class FeedbackLabelViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FeedbackLabelSerializer
    permission_classes = [REVIEW]
    queryset = FeedbackLabel.objects.select_related(
        "channel__node", "rule", "decided_by", "reviewed_by", "incident", "last_used_model"
    ).order_by("-created_at")
    filterset_fields = (
        "status",
        "effect",
        "source",
        "rule",
        "decided_by",
        "decision",
        "incident",
        "last_used_model",
    )
    search_fields = ("channel__name", "incident__title", "review_comment")

    @action(detail=False, methods=["post"])
    def review(self, request):
        """Принять/отклонить метки: списком, всем решением, всеми метками диспетчера или правила."""
        data = BulkReviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        qs = FeedbackLabel.objects.all()
        if v.get("ids"):
            qs = qs.filter(pk__in=v["ids"])
        for key in ("decision", "decided_by", "rule"):
            if v.get(key):
                qs = qs.filter(**{f"{key}_id": v[key]})
        if v.get("source"):
            qs = qs.filter(source=v["source"])
        if v.get("only_status"):
            qs = qs.filter(status=v["only_status"])
        changed = feedback.review(qs.exclude(status=v["status"]), request.user, v["status"], v["comment"])
        payload = {k: val for k, val in v.items() if k != "comment"} | {"changed": changed}
        log_action(request, "feedback.review", payload=payload)
        return Response({"changed": changed})

    @action(detail=False)
    def summary(self, request):
        qs = self.filter_queryset(self.get_queryset())
        by_status = dict(qs.values_list("status").annotate(n=Count("pk")).order_by())
        by_effect = dict(
            qs.filter(status=FeedbackLabel.Status.ACCEPTED)
            .values_list("effect")
            .annotate(n=Count("pk"))
            .order_by()
        )
        rows = (
            qs.exclude(decided_by=None)
            .values("decided_by", "decided_by__last_name", "decided_by__first_name", "decided_by__username")
            .annotate(
                total=Count("pk"),
                accepted=Count("pk", filter=Q(status=FeedbackLabel.Status.ACCEPTED)),
                rejected=Count("pk", filter=Q(status=FeedbackLabel.Status.REJECTED)),
            )
            .order_by("-total")
        )
        by_dispatcher = [
            {
                "user": row["decided_by"],
                "name": " ".join(filter(None, [row["decided_by__last_name"], row["decided_by__first_name"]]))
                or row["decided_by__username"],
                "total": row["total"],
                "accepted": row["accepted"],
                "rejected": row["rejected"],
            }
            for row in rows
        ]
        emulated = (
            qs.filter(source=FeedbackLabel.Source.EMULATED)
            .exclude(status=FeedbackLabel.Status.REJECTED)
            .count()
        )
        not_used = qs.filter(status=FeedbackLabel.Status.ACCEPTED, last_used_model=None).count()
        return Response(
            {
                "by_status": by_status,
                "accepted_by_effect": by_effect,
                "by_dispatcher": by_dispatcher,
                "accepted_not_in_model": not_used,
                "emulated_active": emulated,
            }
        )


class LearningSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningSettings
        exclude = ("id",)
        read_only_fields = ("last_check",)


class LearningSettingsView(APIView):
    permission_classes = [REVIEW]

    def get(self, request):
        return Response(LearningSettingsSerializer(LearningSettings.load()).data)

    def patch(self, request):
        serializer = LearningSettingsSerializer(LearningSettings.load(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_action(request, "feedback.settings", payload=dict(serializer.validated_data))
        return Response(serializer.data)

    def post(self, request):
        """Проверить деградацию сейчас."""
        from ..training import check_degradation

        return Response(check_degradation(), status=status.HTTP_200_OK)
