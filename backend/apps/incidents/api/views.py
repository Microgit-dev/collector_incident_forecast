from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.services import log_action
from apps.core.permissions import require_perm
from apps.topology.mixins import ScopedQuerySetMixin

from .. import services
from ..models import (
    Alert,
    Decision,
    DecisionOutcome,
    DecisionReason,
    EscalationPolicy,
    Incident,
    IncidentEvent,
)


class AlertSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source="channel.name", default=None, read_only=True)

    class Meta:
        model = Alert
        fields = (
            "id",
            "incident",
            "source",
            "type",
            "severity",
            "node",
            "channel",
            "channel_name",
            "prediction",
            "raised_at",
            "title",
            "details",
            "acknowledged_by",
            "acknowledged_at",
        )


class DecisionSerializer(serializers.ModelSerializer):
    decided_by_name = serializers.CharField(source="decided_by.get_full_name", read_only=True)

    class Meta:
        model = Decision
        fields = (
            "id",
            "incident",
            "outcome",
            "reason",
            "comment",
            "decided_by",
            "decided_by_name",
            "decided_at",
        )


class IncidentEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.get_full_name", default=None, read_only=True)

    class Meta:
        model = IncidentEvent
        fields = ("id", "ts", "kind", "actor", "actor_name", "text", "payload")


class IncidentSerializer(serializers.ModelSerializer):
    node_name = serializers.CharField(source="node.name", read_only=True)
    responsible_node_name = serializers.CharField(source="responsible_node.name", read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.get_full_name", default=None, read_only=True)
    alerts_count = serializers.IntegerField(source="alerts.count", read_only=True)

    class Meta:
        model = Incident
        fields = (
            "id",
            "type",
            "severity",
            "status",
            "is_forecast",
            "node",
            "node_name",
            "responsible_node",
            "responsible_node_name",
            "title",
            "description",
            "probability",
            "horizon_hours",
            "opened_at",
            "ack_deadline",
            "acknowledged_at",
            "resolved_at",
            "assigned_to",
            "assigned_to_name",
            "escalation_level",
            "alerts_count",
        )
        read_only_fields = fields


class IncidentDetailSerializer(IncidentSerializer):
    alerts = AlertSerializer(many=True, read_only=True)
    decisions = DecisionSerializer(many=True, read_only=True)
    events = IncidentEventSerializer(many=True, read_only=True)

    class Meta(IncidentSerializer.Meta):
        fields = (*IncidentSerializer.Meta.fields, "alerts", "decisions", "events")
        read_only_fields = fields


class DecideSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=DecisionOutcome.choices)
    reason = serializers.PrimaryKeyRelatedField(
        queryset=DecisionReason.objects.filter(is_active=True), required=False, allow_null=True
    )
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class IncidentViewSet(ScopedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Инциденты в зоне ответственности. Действия цепочки командования — отдельные POST-эндпоинты,
    каждое со своим правом и записью в журнал действий.
    """

    queryset = Incident.objects.select_related("node", "responsible_node", "assigned_to")
    filterset_fields = {
        "type": ["exact", "in"],
        "severity": ["exact", "in"],
        "status": ["exact", "in"],
        "node": ["exact"],
        "is_forecast": ["exact"],
        "assigned_to": ["exact", "isnull"],
        "opened_at": ["gte", "lt"],
    }
    search_fields = ("title", "node__name")
    ordering_fields = ("opened_at", "severity", "ack_deadline")

    def get_serializer_class(self):
        return IncidentDetailSerializer if self.action == "retrieve" else IncidentSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "retrieve":
            qs = qs.prefetch_related("alerts__channel", "decisions__decided_by", "events__actor")
        return qs

    def _run(self, request, action_name: str, fn, *args, **kwargs):
        incident = self.get_object()
        try:
            result = fn(incident, request.user, *args, **kwargs)
        except services.IncidentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        log_action(
            request,
            f"incident.{action_name}",
            obj=incident,
            payload=kwargs and {k: str(v) for k, v in kwargs.items()},
        )
        incident.refresh_from_db()
        body = IncidentDetailSerializer(incident).data
        if isinstance(result, Decision):
            body["decision"] = DecisionSerializer(result).data
        return Response(body)

    @action(detail=True, methods=["post"], permission_classes=[require_perm("incidents.acknowledge_alert")])
    def acknowledge(self, request, pk=None):
        return self._run(request, "acknowledge", services.acknowledge)

    @action(detail=True, methods=["post"], permission_classes=[require_perm("incidents.change_incident")])
    def take(self, request, pk=None):
        return self._run(request, "take", services.take, force=bool(request.data.get("force")))

    @action(detail=True, methods=["post"], permission_classes=[require_perm("incidents.change_incident")])
    def release(self, request, pk=None):
        return self._run(request, "release", services.release)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[require_perm("incidents.decide_incident")],
        serializer_class=DecideSerializer,
    )
    def decide(self, request, pk=None):
        data = DecideSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self._run(request, "decide", services.decide, **data.validated_data)

    @action(detail=True, methods=["post"], permission_classes=[require_perm("incidents.escalate_incident")])
    def escalate(self, request, pk=None):
        incident = self.get_object()
        services.escalate(incident, actor=request.user, reason=request.data.get("reason") or "вручную")
        log_action(request, "incident.escalate", obj=incident)
        incident.refresh_from_db()
        return Response(IncidentDetailSerializer(incident).data)


class AlertViewSet(ScopedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Alert.objects.select_related("channel")
    serializer_class = AlertSerializer
    filterset_fields = {
        "type": ["exact"],
        "severity": ["exact", "in"],
        "source": ["exact"],
        "incident": ["exact"],
        "raised_at": ["gte", "lt"],
    }


class DecisionReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = DecisionReason
        fields = ("id", "code", "name", "outcome", "incident_types", "is_active")


class DecisionReasonViewSet(viewsets.ModelViewSet):
    queryset = DecisionReason.objects.all()
    serializer_class = DecisionReasonSerializer
    filterset_fields = ("outcome", "is_active")


class EscalationPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = EscalationPolicy
        fields = ("id", "severity", "ack_timeout_minutes", "max_level", "repeat_notify_minutes")


class EscalationPolicyViewSet(viewsets.ModelViewSet):
    queryset = EscalationPolicy.objects.all()
    serializer_class = EscalationPolicySerializer
