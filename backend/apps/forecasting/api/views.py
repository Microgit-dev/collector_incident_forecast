from django.db.models import Avg, Count, Max, Q
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.selectors import viewers
from apps.audit.services import log_action, log_view
from apps.core.permissions import require_perm
from apps.topology.mixins import ScopedQuerySetMixin

from ..models import ChannelHealth, ChannelRisk, MLModel, Prediction, RiskPolicy, RiskSnapshot, TrainingRun


class MLModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = MLModel
        fields = (
            "id",
            "task",
            "version",
            "algorithm",
            "horizon_hours",
            "status",
            "features",
            "params",
            "metrics",
            "train_period",
            "notes",
            "created_at",
        )


class RiskPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskPolicy
        fields = (
            "id",
            "task",
            "medium_threshold",
            "high_threshold",
            "critical_threshold",
            "alert_from_level",
            "horizon_hours",
            "enabled",
        )


class PredictionSerializer(serializers.ModelSerializer):
    node_name = serializers.CharField(source="node.name", read_only=True)
    channel_name = serializers.CharField(source="channel.name", default=None, read_only=True)

    class Meta:
        model = Prediction
        fields = (
            "id",
            "task",
            "model",
            "node",
            "node_name",
            "channel",
            "channel_name",
            "issued_at",
            "horizon_hours",
            "valid_until",
            "probability",
            "risk_level",
            "factors",
            "summary",
            "outcome",
            "outcome_at",
            "is_backtest",
        )


class TrainingRunSerializer(serializers.ModelSerializer):
    started_by_name = serializers.CharField(source="started_by.get_full_name", default=None, read_only=True)

    class Meta:
        model = TrainingRun
        fields = (
            "id",
            "task",
            "status",
            "params",
            "result_model",
            "log",
            "progress",
            "stage",
            "started_by_name",
            "created_at",
            "updated_at",
            "finished_at",
        )
        read_only_fields = ("status", "result_model", "log", "progress", "stage", "finished_at")


class MLModelViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MLModel.objects.all().order_by("-created_at")
    serializer_class = MLModelSerializer
    filterset_fields = ("task", "status")

    @action(detail=True, methods=["post"], permission_classes=[require_perm("forecasting.retrain_model")])
    def activate(self, request, pk=None):
        from ..services import activate

        model = activate(self.get_object())
        log_action(request, "forecasting.activate", obj=model)
        return Response(self.get_serializer(model).data)


class RiskPolicyViewSet(viewsets.ModelViewSet):
    queryset = RiskPolicy.objects.all()
    serializer_class = RiskPolicySerializer


class PredictionViewSet(ScopedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Prediction.objects.select_related("node", "channel")
    serializer_class = PredictionSerializer
    filterset_fields = {
        "task": ["exact"],
        "risk_level": ["exact", "in"],
        "outcome": ["exact"],
        "node": ["exact"],
        "channel": ["exact"],
        "issued_at": ["gte", "lt"],
        "is_backtest": ["exact"],
    }
    ordering_fields = ("issued_at", "probability")

    @action(detail=False)
    def summary(self, request):
        """Итог отработки журнала: сколько прогнозов подтвердилось (реализованная точность)."""
        qs = self.filter_queryset(self.get_queryset())
        counts = dict(qs.values_list("outcome").annotate(n=Count("pk")))
        resolved = counts.get("confirmed", 0) + counts.get("not_confirmed", 0)
        return Response(
            {
                "by_outcome": counts,
                "total": sum(counts.values()),
                "precision": round(counts.get("confirmed", 0) / resolved, 3) if resolved else None,
            }
        )

    def retrieve(self, request, *args, **kwargs):
        prediction = self.get_object()
        log_view(request, prediction, "prediction.view")
        return Response(
            self.get_serializer(prediction).data | {"viewed_by": viewers(prediction, "prediction.view")}
        )


class TrainingRunViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    queryset = TrainingRun.objects.select_related("result_model")
    serializer_class = TrainingRunSerializer
    filterset_fields = ("task", "status")

    def get_permissions(self):
        if self.action == "create":
            return [require_perm("forecasting.retrain_model")()]
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
        active = [TrainingRun.Status.PENDING, TrainingRun.Status.RUNNING]
        if TrainingRun.objects.filter(status__in=active).exists():
            return Response({"detail": "Обучение уже выполняется"}, status=status.HTTP_409_CONFLICT)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = serializer.save(started_by=request.user)
        from ..tasks import train_model

        train_model.delay(run.pk)
        log_action(request, "forecasting.retrain", obj=run, payload={"task": run.task})
        return Response(self.get_serializer(run).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=False)
    def tasks(self, request):
        from ..models import ForecastTask

        return Response([{"value": v, "label": label} for v, label in ForecastTask.choices])


class ChannelRiskSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source="channel.name", read_only=True)
    node = serializers.IntegerField(source="channel.node_id", read_only=True)
    node_name = serializers.CharField(source="channel.node.name", read_only=True)
    sensor_type = serializers.CharField(source="channel.sensor_type.name", default=None, read_only=True)
    picket = serializers.DecimalField(source="channel.picket", max_digits=8, decimal_places=2, read_only=True)

    class Meta:
        model = ChannelRisk
        fields = (
            "id",
            "channel",
            "channel_name",
            "node",
            "node_name",
            "sensor_type",
            "picket",
            "task",
            "as_of",
            "probability",
            "risk_level",
            "factors",
        )


class ChannelRiskViewSet(ScopedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    """Текущий риск по каналам — очередь «что проверить в первую очередь»."""

    queryset = ChannelRisk.objects.select_related("channel__node", "channel__sensor_type").order_by(
        "-probability"
    )
    serializer_class = ChannelRiskSerializer
    scope_field = "channel__node"
    filterset_fields = {"task": ["exact"], "risk_level": ["exact", "in"], "channel__node": ["exact"]}
    ordering_fields = ("probability",)


class ChannelHealthSerializer(serializers.ModelSerializer):
    channel_name = serializers.CharField(source="channel.name", read_only=True)
    node = serializers.IntegerField(source="channel.node_id", read_only=True)
    node_name = serializers.CharField(source="channel.node.name", read_only=True)
    sensor_type = serializers.CharField(source="channel.sensor_type.name", default=None, read_only=True)

    class Meta:
        model = ChannelHealth
        fields = (
            "channel",
            "channel_name",
            "node",
            "node_name",
            "sensor_type",
            "computed_at",
            "score",
            "components",
            "periodic",
            "expected_interval_s",
            "last_seen_at",
            "silent",
            "silent_since",
        )


class ChannelHealthViewSet(ScopedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = ChannelHealth.objects.select_related("channel__node", "channel__sensor_type").order_by("score")
    serializer_class = ChannelHealthSerializer
    scope_field = "channel__node"
    filterset_fields = {
        "score": ["lt", "gte"],
        "silent": ["exact"],
        "periodic": ["exact"],
        "channel__node": ["exact"],
    }
    ordering_fields = ("score", "last_seen_at")

    @action(detail=False)
    def summary(self, request):
        qs = self.filter_queryset(self.get_queryset())
        return Response(
            qs.aggregate(
                total=Count("pk"),
                good=Count("pk", filter=Q(score__gte=80)),
                degraded=Count("pk", filter=Q(score__gte=50, score__lt=80)),
                poor=Count("pk", filter=Q(score__lt=50)),
                silent=Count("pk", filter=Q(silent=True)),
                periodic=Count("pk", filter=Q(periodic=True)),
                average=Avg("score"),
                computed_at=Max("computed_at"),
            )
        )


class NodeRiskViewSet(ScopedQuerySetMixin, viewsets.GenericViewSet):
    """Последний снимок риска по каждому объекту (для дашборда и схемы)."""

    scope_field = "node"
    queryset = RiskSnapshot.objects.all()

    def get_queryset(self):
        latest = RiskSnapshot.objects.aggregate(m=Max("as_of"))["m"]
        qs = RiskSnapshot.objects.filter(as_of=latest).select_related("node").order_by("-max_probability")
        return self.scope(qs)

    def scope(self, qs):
        from apps.topology.selectors import scope_queryset

        return scope_queryset(qs, self.request.user, "node")

    def list(self, request):
        return Response(
            [
                {
                    "node": s.node_id,
                    "node_name": s.node.name,
                    "task": s.task,
                    "as_of": s.as_of,
                    "max_probability": s.max_probability,
                    "expected_failures": s.expected_failures,
                    "channels_total": s.channels_total,
                    "channels_at_risk": s.channels_at_risk,
                    "risk_level": s.risk_level,
                }
                for s in self.get_queryset()
            ]
        )


class CycleViewSet(viewsets.ViewSet):
    """Внеочередной цикл прогноза (кнопка у аналитика)."""

    def get_permissions(self):
        return [require_perm("forecasting.retrain_model")()]

    def create(self, request):
        from ..tasks import run_forecast_cycle

        run_forecast_cycle.delay()
        log_action(request, "forecasting.cycle")
        return Response({"detail": "Цикл прогноза запущен"}, status=status.HTTP_202_ACCEPTED)

    @action(detail=False, methods=["post"])
    def backtest(self, request):
        from ..tasks import backtest_recent

        days = min(max(int(request.data.get("days", 30)), 1), 365)
        backtest_recent.delay(days)
        log_action(request, "forecasting.backtest", payload={"days": days})
        return Response(
            {"detail": f"Бэктест за {days} суток запущен — результаты появятся в журнале прогнозов"},
            status=status.HTTP_202_ACCEPTED,
        )
