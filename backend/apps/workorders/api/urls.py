from rest_framework.routers import DefaultRouter

from .views import RecommendationViewSet, WorkOrderViewSet

router = DefaultRouter()
router.register("workorders/items", WorkOrderViewSet)
router.register("workorders/recommendations", RecommendationViewSet)

urlpatterns = router.urls
