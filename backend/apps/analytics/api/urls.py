from django.urls import path

from .views import FloodView, OverviewView, ReplayView

urlpatterns = [
    path("analytics/overview/", OverviewView.as_view(), name="analytics-overview"),
    path("analytics/flood/", FloodView.as_view(), name="analytics-flood"),
    path("analytics/replay/", ReplayView.as_view(), name="analytics-replay"),
]
