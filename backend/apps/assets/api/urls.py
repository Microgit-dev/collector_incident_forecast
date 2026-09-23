from rest_framework.routers import DefaultRouter

from .views import ChannelViewSet, EquipmentViewSet, SensorTypeViewSet

router = DefaultRouter()
router.register("assets/sensor-types", SensorTypeViewSet)
router.register("assets/channels", ChannelViewSet)
router.register("assets/equipment", EquipmentViewSet)

urlpatterns = router.urls
