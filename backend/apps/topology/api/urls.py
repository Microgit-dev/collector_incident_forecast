from django.urls import path
from rest_framework.routers import DefaultRouter

from .structure import (
    DetectBuildingView,
    ObjectDetailView,
    ObjectsView,
    SecondmentRecallView,
    SensorDetailView,
    SensorsView,
    StaffActionView,
    StructureView,
    ZoneDetailView,
    ZonesView,
)
from .views import NodeViewSet

router = DefaultRouter()
router.register("topology/nodes", NodeViewSet)

urlpatterns = [
    path("topology/structure/", StructureView.as_view(), name="structure"),
    path("topology/zones/", ZonesView.as_view(), name="zones"),
    path("topology/zones/<int:pk>/", ZoneDetailView.as_view(), name="zone-detail"),
    path("topology/objects/", ObjectsView.as_view(), name="objects"),
    path("topology/objects/<int:pk>/", ObjectDetailView.as_view(), name="object-detail"),
    path("topology/sensors/", SensorsView.as_view(), name="sensors"),
    path("topology/sensors/<int:pk>/", SensorDetailView.as_view(), name="sensor-detail"),
    path("topology/detect-building/", DetectBuildingView.as_view(), name="detect-building"),
    path("topology/staff/<int:pk>/<str:action>/", StaffActionView.as_view(), name="staff-action"),
    path("topology/secondments/<int:pk>/recall/", SecondmentRecallView.as_view(), name="secondment-recall"),
    *router.urls,
]
