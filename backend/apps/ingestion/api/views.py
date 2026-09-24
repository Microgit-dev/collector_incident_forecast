import tempfile
from pathlib import Path

from django.conf import settings
from django.db import transaction
from rest_framework import serializers, status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assets.services import import_channels
from apps.audit.services import log_action
from apps.core.permissions import require_perm
from apps.topology.services import import_objects

from .. import history
from ..adapters import REGISTRY
from ..models import DataSource, ImportJob

UPLOAD_SUFFIXES = {".csv", ".xlsx", ".xlsm"}


class DataSourceSerializer(serializers.ModelSerializer):
    adapter = serializers.ChoiceField(choices=sorted(REGISTRY))

    class Meta:
        model = DataSource
        fields = ("id", "code", "name", "kind", "adapter", "config", "is_active", "read_only")


class ImportJobSerializer(serializers.ModelSerializer):
    source = serializers.PrimaryKeyRelatedField(queryset=DataSource.objects.all(), required=False)
    file_name = serializers.SerializerMethodField()

    class Meta:
        model = ImportJob
        fields = (
            "id",
            "kind",
            "batch",
            "source",
            "file",
            "file_name",
            "file_path",
            "params",
            "status",
            "progress",
            "stage",
            "rows_total",
            "rows_ok",
            "rows_skipped",
            "started_at",
            "finished_at",
            "error",
            "quality",
            "created_at",
        )
        read_only_fields = (
            "kind",
            "batch",
            "status",
            "progress",
            "stage",
            "rows_total",
            "rows_ok",
            "rows_skipped",
            "started_at",
            "finished_at",
            "error",
            "quality",
        )

    def get_file_name(self, obj: ImportJob) -> str:
        return Path(obj.file.name or obj.file_path).name

    def validate_file(self, value):
        if value and Path(value.name).suffix.lower() not in UPLOAD_SUFFIXES:
            raise serializers.ValidationError("Поддерживаются журналы в CSV и XLSX")
        return value

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
    filterset_fields = ("source", "status", "kind", "batch")
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        source = (
            serializer.validated_data.get("source")
            or DataSource.objects.get_or_create(
                code="smvu-upload",
                defaults={
                    "name": "Загрузка файла журнала",
                    "kind": DataSource.Kind.FILE,
                    "adapter": "smvu_csv",
                },
            )[0]
        )
        job = serializer.save(
            created_by=self.request.user, source=source, kind=ImportJob.Kind.FILE, stage="В очереди"
        )
        log_action(
            self.request, "ingestion.upload", obj=job, payload={"file": job.file.name or job.file_path}
        )
        from ..tasks import run_import_job

        transaction.on_commit(lambda: run_import_job.delay(job.pk))


class HistorySerializer(serializers.Serializer):
    years = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    raw_days = serializers.IntegerField(min_value=1, max_value=365, default=30)


class HistoryView(APIView):
    """Импорт истории журналов из каталога данных: что есть, что загружено, запуск пакета."""

    def get_permissions(self):
        return [require_perm("ingestion.add_importjob")()]

    def get(self, request):
        active = (
            ImportJob.objects.filter(kind__in=["history", "window"], status__in=history.ACTIVE)
            .values_list("batch", flat=True)
            .first()
        )
        return Response(
            {
                "data_dir": str(settings.DATA_DIR),
                "journals_dir": str(history.journals_dir()),
                "journals": history.available_journals(),
                "reference": history.reference_status(),
                "active_batch": active,
            }
        )

    def post(self, request):
        data = HistorySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            batch = history.plan(data.validated_data["years"], data.validated_data["raw_days"], request.user)
        except history.ImportBusy as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except (FileNotFoundError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        from ..tasks import run_history_batch

        transaction.on_commit(lambda: run_history_batch.delay(str(batch)))
        log_action(request, "ingestion.history", payload=data.validated_data)
        return Response({"batch": batch}, status=status.HTTP_202_ACCEPTED)


class ReferenceView(APIView):
    """
    Справочники: загрузка файлами из браузера или из каталога данных сервера.
    Выполняется синхронно — это секунды, а пользователь сразу видит результат.
    """

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        return [require_perm("ingestion.add_importjob")()]

    def post(self, request):
        base = settings.DATA_DIR / "dataset"
        objects = request.FILES.get("objects")
        channels = request.FILES.get("channels")
        result = {}
        with tempfile.TemporaryDirectory() as tmp:
            objects_path = _save(objects, tmp) if objects else base / "справочник_объектов_диспетчер.csv"
            channels_path = _save(channels, tmp) if channels else base / "справочник_каналов_датчиков.csv"
            if not (objects or channels) and not request.data.get("from_data_dir"):
                return Response({"detail": "Приложите файлы справочников"}, status=400)
            try:
                if objects or not channels:
                    result["objects"] = import_objects(objects_path)
                if channels or not objects:
                    result["channels"] = import_channels(channels_path)
            except (FileNotFoundError, KeyError, ValueError) as exc:
                return Response({"detail": f"Не удалось загрузить справочник: {exc}"}, status=400)
        log_action(request, "ingestion.reference", payload=result)
        return Response({**result, "reference": history.reference_status()})


def _save(upload, directory: str) -> Path:
    path = Path(directory) / Path(upload.name).name
    with open(path, "wb") as fh:
        for chunk in upload.chunks():
            fh.write(chunk)
    return path
