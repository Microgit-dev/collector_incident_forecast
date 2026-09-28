import tempfile
from pathlib import Path

from django.conf import settings
from django.db import transaction
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.demo import attach_missing_scopes
from apps.assets.registry import emulate_registry
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
                    result["equipment"] = emulate_registry()
                result["team_scopes"] = attach_missing_scopes()
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


# ---------------------------------------------------------------- конструктор источников


class TemplateSourceSerializer(serializers.ModelSerializer):
    """Источник-шаблон конструктора: формат, поля, пример, ключ приёма по HTTP."""

    ingest_url = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source="created_by.get_full_name", default=None, read_only=True)

    class Meta:
        model = DataSource
        fields = (
            "id",
            "code",
            "name",
            "description",
            "kind",
            "format",
            "config",
            "sample",
            "is_active",
            "token",
            "ingest_url",
            "created_by_name",
            "updated_at",
        )
        read_only_fields = ("token", "created_by_name", "updated_at")
        extra_kwargs = {"kind": {"required": False}}

    def get_ingest_url(self, obj) -> str:
        return f"/api/v1/ingestion/templates/{obj.code}/events/"

    def validate_format(self, value):
        from ..templates import FORMATS

        if value not in FORMATS:
            raise serializers.ValidationError("Формат: json, csv или regex")
        return value


class TemplateSourceViewSet(viewsets.ModelViewSet):
    """
    Конструктор: шаблоны формата сообщений (adapter=template). Песочница проверяет разбор и нормализацию
    на примере; ключ приёма выдаётся при создании и меняется действием rotate-token.
    """

    serializer_class = TemplateSourceSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        from ..constructor import TEMPLATE_ADAPTER

        return (
            DataSource.objects.filter(adapter=TEMPLATE_ADAPTER).select_related("created_by").order_by("name")
        )

    def get_permissions(self):

        if self.action in ("list", "retrieve", "library", "preview"):
            return [require_perm("ingestion.view_datasource")()]
        return [require_perm("ingestion.change_datasource")()]

    def perform_create(self, serializer):
        from ..constructor import TEMPLATE_ADAPTER, new_token

        kind = serializer.validated_data.get("kind") or DataSource.Kind.STREAM
        source = serializer.save(
            adapter=TEMPLATE_ADAPTER, kind=kind, token=new_token(), created_by=self.request.user
        )
        log_action(self.request, "constructor.create", obj=source)

    def perform_update(self, serializer):
        source = serializer.save()
        log_action(self.request, "constructor.update", obj=source)

    def perform_destroy(self, instance):
        log_action(self.request, "constructor.delete", payload={"code": instance.code})
        instance.delete()

    @action(detail=False, methods=["get"])
    def library(self, request):
        from ..templates import LIBRARY

        return Response(LIBRARY)

    @action(detail=False, methods=["post"])
    def preview(self, request):
        from ..constructor import preview

        fmt = request.data.get("format")
        config = request.data.get("config") or {}
        sample = str(request.data.get("sample") or "")
        if len(sample) > 200_000:
            return Response({"detail": "Пример больше 200 КБ"}, status=400)
        if not isinstance(config, dict):
            return Response({"detail": "config — объект JSON"}, status=400)
        return Response(preview(fmt, config, sample, request.data.get("profile")))

    @action(detail=True, methods=["post"], url_path="rotate-token")
    def rotate_token(self, request, pk=None):
        from ..constructor import new_token

        source = self.get_object()
        source.token = new_token()
        source.save(update_fields=["token", "updated_at"])
        log_action(request, "constructor.rotate_token", obj=source)
        return Response(self.get_serializer(source).data)


class TemplateIngestView(APIView):
    """
    Приём сообщений от шлюза по шаблону: POST тело сообщения (JSON, CSV или строки) с заголовком
    «Authorization: Token <ключ источника>». События уходят в поток Kafka, как от СМВУ.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request, code: str):
        import hmac

        from ..constructor import MAX_PAYLOAD, TEMPLATE_ADAPTER, ingest

        source = DataSource.objects.filter(code=code, adapter=TEMPLATE_ADAPTER, is_active=True).first()
        header = request.headers.get("Authorization", "")
        token = header.removeprefix("Token ").strip()
        if source is None or not source.token or not hmac.compare_digest(token, source.token):
            return Response({"detail": "Неизвестный источник или неверный ключ"}, status=401)
        body = request.body
        if len(body) > MAX_PAYLOAD:
            return Response({"detail": "Сообщение больше 1 МБ"}, status=413)
        try:
            result = ingest(source, body.decode("utf-8-sig"))
        except UnicodeDecodeError:
            return Response({"detail": "Кодировка сообщения — UTF-8"}, status=400)
        except Exception as exc:  # брокер недоступен — шлюз повторит отправку
            return Response({"detail": f"Поток событий недоступен: {exc}"}, status=503)
        return Response(result, status=202 if result["accepted"] else 400)
