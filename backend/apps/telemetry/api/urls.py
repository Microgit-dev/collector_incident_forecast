from rest_framework.routers import DefaultRouter

from .views import ChannelDailyViewSet, ChannelStateViewSet, ReadingViewSet

router = DefaultRouter()
router.register("telemetry/readings", ReadingViewSet)
router.register("telemetry/channel-states", ChannelStateViewSet)
router.register("telemetry/daily", ChannelDailyViewSet)

urlpatterns = router.urls
