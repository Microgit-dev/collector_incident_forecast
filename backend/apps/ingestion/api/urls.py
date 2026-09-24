from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import DataSourceViewSet, HistoryView, ImportJobViewSet, ReferenceView

router = DefaultRouter()
router.register("ingestion/sources", DataSourceViewSet)
router.register("ingestion/jobs", ImportJobViewSet)

urlpatterns = [
    path("ingestion/history/", HistoryView.as_view(), name="ingestion-history"),
    path("ingestion/reference/", ReferenceView.as_view(), name="ingestion-reference"),
    *router.urls,
]
