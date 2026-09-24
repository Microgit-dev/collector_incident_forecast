from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    EfficiencyView,
    FloodView,
    LiveView,
    OverviewView,
    QualityView,
    RangesView,
    ReplayView,
    ReportViewSet,
    SchemeView,
)

urlpatterns = [
    path("analytics/overview/", OverviewView.as_view(), name="analytics-overview"),
    path("analytics/live/", LiveView.as_view(), name="analytics-live"),
    path("analytics/scheme/", SchemeView.as_view(), name="analytics-scheme"),
    path("analytics/efficiency/", EfficiencyView.as_view(), name="analytics-efficiency"),
    path("analytics/quality/", QualityView.as_view(), name="analytics-quality"),
    path("analytics/ranges/", RangesView.as_view(), name="analytics-ranges"),
    path("analytics/flood/", FloodView.as_view(), name="analytics-flood"),
    path("analytics/replay/", ReplayView.as_view(), name="analytics-replay"),
]

router = DefaultRouter()
router.register("analytics/reports", ReportViewSet, basename="report")
urlpatterns += router.urls
