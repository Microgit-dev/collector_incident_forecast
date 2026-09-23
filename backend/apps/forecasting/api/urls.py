from rest_framework.routers import DefaultRouter

from .views import MLModelViewSet, PredictionViewSet, RiskPolicyViewSet, TrainingRunViewSet

router = DefaultRouter()
router.register("forecasting/models", MLModelViewSet)
router.register("forecasting/policies", RiskPolicyViewSet)
router.register("forecasting/predictions", PredictionViewSet)
router.register("forecasting/training-runs", TrainingRunViewSet)

urlpatterns = router.urls
