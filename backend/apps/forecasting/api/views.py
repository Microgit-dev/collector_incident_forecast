from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.services import log_action
from apps.core.permissions import require_perm
from apps.topology.mixins import ScopedQuerySetMixin

from ..models import MLModel, Prediction, RiskPolicy, TrainingRun


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
        )


class TrainingRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingRun
        fields = ("id", "task", "status", "params", "result_model", "log", "created_at", "finished_at")
        read_only_fields = ("status", "result_model", "log", "finished_at")


class MLModelViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MLModel.objects.all()
    serializer_class = MLModelSerializer
    filterset_fields = ("task", "status")


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
    }
    ordering_fields = ("issued_at", "probability")


class TrainingRunViewSet(mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    queryset = TrainingRun.objects.select_related("result_model")
    serializer_class = TrainingRunSerializer
    filterset_fields = ("task", "status")

    def get_permissions(self):
        if self.action == "create":
            return [require_perm("forecasting.retrain_model")()]
        return super().get_permissions()

    def create(self, request, *args, **kwargs):
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
