from django.urls import path

from .views import FloodView, LiveView, OverviewView, ReplayView, SchemeView

urlpatterns = [
    path("analytics/overview/", OverviewView.as_view(), name="analytics-overview"),
    path("analytics/live/", LiveView.as_view(), name="analytics-live"),
    path("analytics/scheme/", SchemeView.as_view(), name="analytics-scheme"),
    path("analytics/flood/", FloodView.as_view(), name="analytics-flood"),
    path("analytics/replay/", ReplayView.as_view(), name="analytics-replay"),
]
