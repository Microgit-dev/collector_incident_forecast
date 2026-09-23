from rest_framework.routers import DefaultRouter

from .views import DataSourceViewSet, ImportJobViewSet

router = DefaultRouter()
router.register("ingestion/sources", DataSourceViewSet)
router.register("ingestion/jobs", ImportJobViewSet)

urlpatterns = router.urls
