from rest_framework.routers import DefaultRouter

from .views import SensorProfileViewSet, StateRuleViewSet

router = DefaultRouter()
router.register("normalization/profiles", SensorProfileViewSet)
router.register("normalization/rules", StateRuleViewSet)

urlpatterns = router.urls
