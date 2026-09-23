from rest_framework.routers import DefaultRouter

from .views import ChannelStateViewSet, ReadingViewSet

router = DefaultRouter()
router.register("telemetry/readings", ReadingViewSet)
router.register("telemetry/channel-states", ChannelStateViewSet)

urlpatterns = router.urls
