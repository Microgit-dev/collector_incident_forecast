from rest_framework.routers import DefaultRouter

from .views import (
    ChannelHealthViewSet,
    ChannelRiskViewSet,
    CycleViewSet,
    MLModelViewSet,
    NodeRiskViewSet,
    PredictionViewSet,
    RiskPolicyViewSet,
    TrainingRunViewSet,
)

router = DefaultRouter()
router.register("forecasting/models", MLModelViewSet)
router.register("forecasting/policies", RiskPolicyViewSet)
router.register("forecasting/predictions", PredictionViewSet)
router.register("forecasting/training-runs", TrainingRunViewSet)
router.register("forecasting/channel-risk", ChannelRiskViewSet)
router.register("forecasting/health", ChannelHealthViewSet)
router.register("forecasting/node-risk", NodeRiskViewSet, basename="node-risk")
router.register("forecasting/cycle", CycleViewSet, basename="forecast-cycle")

urlpatterns = router.urls
