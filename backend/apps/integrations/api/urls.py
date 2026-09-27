from django.urls import path

from .views import (
    CameraListView,
    CameraSnapshotView,
    IntegrationActionView,
    IntegrationListView,
    RegistryImportView,
)

urlpatterns = [
    path("integrations/", IntegrationListView.as_view(), name="integrations"),
    path("integrations/registry/import/", RegistryImportView.as_view(), name="registry-import"),
    path("integrations/cameras/", CameraListView.as_view(), name="cameras"),
    path("integrations/cameras/<int:pk>/snapshot/", CameraSnapshotView.as_view(), name="camera-snapshot"),
    path(
        "integrations/<slug:code>/<slug:action>/", IntegrationActionView.as_view(), name="integration-action"
    ),
]
