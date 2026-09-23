from django.conf import settings
from rest_framework import serializers, viewsets

from ..adapters import REGISTRY
from ..models import DataSource, ImportJob


class DataSourceSerializer(serializers.ModelSerializer):
    adapter = serializers.ChoiceField(choices=sorted(REGISTRY))

    class Meta:
        model = DataSource
        fields = ("id", "code", "name", "kind", "adapter", "config", "is_active", "read_only")


class ImportJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportJob
        fields = (
            "id",
            "source",
            "file",
            "file_path",
            "params",
            "status",
            "rows_total",
            "rows_ok",
            "rows_skipped",
            "started_at",
            "finished_at",
            "error",
            "created_at",
        )
        read_only_fields = (
            "status",
            "rows_total",
            "rows_ok",
            "rows_skipped",
            "started_at",
            "finished_at",
            "error",
        )

    def validate_file_path(self, value: str) -> str:
        # Серверные файлы — только из смонтированного каталога данных, без выхода за его пределы
        if not value:
            return value
        resolved = (settings.DATA_DIR / value).resolve()
        if not resolved.is_relative_to(settings.DATA_DIR.resolve()) or not resolved.is_file():
            raise serializers.ValidationError("Файл не найден в каталоге данных")
        return str(resolved)

    def validate(self, attrs):
        if not attrs.get("file") and not attrs.get("file_path"):
            raise serializers.ValidationError("Нужен файл или путь к файлу в каталоге данных")
        return attrs


class DataSourceViewSet(viewsets.ModelViewSet):
    queryset = DataSource.objects.all()
    serializer_class = DataSourceSerializer


class ImportJobViewSet(viewsets.ModelViewSet):
    queryset = ImportJob.objects.select_related("source")
    serializer_class = ImportJobSerializer
    filterset_fields = ("source", "status")
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        job = serializer.save(created_by=self.request.user)
        from ..tasks import run_import_job

        run_import_job.delay(job.pk)
