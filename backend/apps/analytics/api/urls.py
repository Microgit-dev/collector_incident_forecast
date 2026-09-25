from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    EfficiencyView,
    FloodView,
    HistoryChannelView,
    HistoryCoverageView,
    HistoryNodeView,
    LiveView,
    OverviewView,
    QualityView,
    RangesView,
    ReplayView,
    ReportViewSet,
    SchemeView,
    WorkspaceView,
)

urlpatterns = [
    path("analytics/overview/", OverviewView.as_view(), name="analytics-overview"),
    path("analytics/workspace/", WorkspaceView.as_view(), name="analytics-workspace"),
    path("analytics/live/", LiveView.as_view(), name="analytics-live"),
    path("analytics/scheme/", SchemeView.as_view(), name="analytics-scheme"),
    path("analytics/efficiency/", EfficiencyView.as_view(), name="analytics-efficiency"),
    path("analytics/quality/", QualityView.as_view(), name="analytics-quality"),
    path("analytics/ranges/", RangesView.as_view(), name="analytics-ranges"),
    path("analytics/flood/", FloodView.as_view(), name="analytics-flood"),
    path("analytics/replay/", ReplayView.as_view(), name="analytics-replay"),
    path("history/channel/", HistoryChannelView.as_view(), name="history-channel"),
    path("history/node/", HistoryNodeView.as_view(), name="history-node"),
    path("history/coverage/", HistoryCoverageView.as_view(), name="history-coverage"),
]

router = DefaultRouter()
router.register("analytics/reports", ReportViewSet, basename="report")
urlpatterns += router.urls
