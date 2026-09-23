from rest_framework.routers import DefaultRouter

from .views import NodeViewSet

router = DefaultRouter()
router.register("topology/nodes", NodeViewSet)

urlpatterns = router.urls
