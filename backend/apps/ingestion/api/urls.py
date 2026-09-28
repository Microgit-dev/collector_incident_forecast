from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    DataSourceViewSet,
    HistoryView,
    ImportJobViewSet,
    ReferenceView,
    TemplateIngestView,
    TemplateSourceViewSet,
)

router = DefaultRouter()
router.register("ingestion/sources", DataSourceViewSet)
router.register("ingestion/jobs", ImportJobViewSet)
router.register("ingestion/templates", TemplateSourceViewSet, basename="template-source")

urlpatterns = [
    path("ingestion/history/", HistoryView.as_view(), name="ingestion-history"),
    path("ingestion/reference/", ReferenceView.as_view(), name="ingestion-reference"),
    path("ingestion/templates/<slug:code>/events/", TemplateIngestView.as_view(), name="template-ingest"),
    *router.urls,
]
