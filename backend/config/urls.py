from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core.views import health

admin.site.site_header = "Collector Forecast — администрирование"
admin.site.site_title = "Collector Forecast"

api_v1 = [
    path("", include("apps.accounts.api.urls")),
    path("", include("apps.topology.api.urls")),
    path("", include("apps.assets.api.urls")),
    path("", include("apps.normalization.api.urls")),
    path("", include("apps.ingestion.api.urls")),
    path("", include("apps.telemetry.api.urls")),
    path("", include("apps.forecasting.api.urls")),
    path("", include("apps.incidents.api.urls")),
    path("", include("apps.workorders.api.urls")),
    path("", include("apps.notifications.api.urls")),
    path("", include("apps.analytics.api.urls")),
    path("", include("apps.training.api.urls")),
    path("", include("apps.wiki.api.urls")),
    path("", include("apps.audit.api.urls")),
    path("", include("apps.integrations.api.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger"),
    path("health/", health, name="health"),
    path("", include("django_prometheus.urls")),  # /metrics
]
