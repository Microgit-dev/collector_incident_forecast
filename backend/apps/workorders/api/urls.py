from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    InspectionViewSet,
    MaintenancePlanView,
    MaintenanceScheduleView,
    RecommendationViewSet,
    WorkOrderViewSet,
)

router = DefaultRouter()
router.register("workorders/items", WorkOrderViewSet)
router.register("workorders/recommendations", RecommendationViewSet)
router.register("workorders/inspections", InspectionViewSet)

urlpatterns = [
    path("workorders/maintenance/plan/", MaintenancePlanView.as_view(), name="maintenance-plan"),
    path("workorders/maintenance/schedule/", MaintenanceScheduleView.as_view(), name="maintenance-schedule"),
    *router.urls,
]
