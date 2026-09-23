from rest_framework.routers import DefaultRouter

from .views import ActionLogViewSet

router = DefaultRouter()
router.register("audit/actions", ActionLogViewSet)

urlpatterns = router.urls
