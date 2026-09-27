from datetime import timedelta

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assets.models import Camera
from apps.audit.services import log_action
from apps.core.permissions import require_perm
from apps.forecasting.models import Prediction
from apps.incidents.models import Incident, IncidentEvent
from apps.topology.models import Node
from apps.topology.selectors import in_scope, scope_queryset

from .. import registry, video

MANAGE = "integrations.manage_integrations"
MAX_REGISTRY_FILE = 50 * 2**20


class IntegrationListView(APIView):
    """Внешние системы: режим, адрес, последний обмен и ошибка (страница «Интеграции»)."""

    permission_classes = [require_perm(MANAGE)]

    def get(self, request):
        return Response(registry.overview())


class IntegrationActionView(APIView):
    """POST check — проверить связь; POST sync — синхронизировать сейчас."""

    permission_classes = [require_perm(MANAGE)]

    def post(self, request, code: str, action: str):
        if code not in registry.BY_CODE or action not in {"check", "sync"}:
            return Response({"detail": "Неизвестная интеграция или действие"}, status=404)
        result = registry.check(code) if action == "check" else registry.sync(code)
        log_action(request, f"integration.{action}", payload={"code": code, "ok": result["ok"]})
        return Response(result)


class RegistryImportView(APIView):
    """Загрузка выгрузки реестра оборудования (CSV/XLSX); GET — шаблон файла."""

    permission_classes = [require_perm("assets.add_equipment")]
    parser_classes = [MultiPartParser]

    def get(self, request):
        from apps.assets.registry_sync import template_csv

        response = HttpResponse(("﻿" + template_csv()).encode("utf-8"), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="equipment_registry_template.csv"'
        return response

    def post(self, request):
        from apps.assets.registry_sync import RegistryError, apply, read_file

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Приложите файл реестра (CSV или XLSX)"}, status=400)
        if upload.size > MAX_REGISTRY_FILE:
            return Response({"detail": "Файл больше 50 МБ"}, status=400)
        try:
            rows = read_file(upload.name, upload.read())
        except (RegistryError, ValueError, UnicodeDecodeError, KeyError) as exc:
            return Response({"detail": f"Не удалось прочитать файл: {exc}"}, status=400)
        full = str(request.data.get("full", "true")).lower() in {"1", "true", "yes"}
        result = apply(rows, full=full)
        registry.mark("registry", True, {k: v for k, v in result.items() if k != "errors"})
        log_action(
            request,
            "registry.import",
            payload={"file": upload.name, **{k: v for k, v in result.items() if k != "errors"}},
        )
        return Response(result)


def _moment(value: str | None):
    if not value:
        return None
    moment = parse_datetime(value)
    if moment is None:
        return None
    return moment if timezone.is_aware(moment) else timezone.make_aware(moment)


def _place(request) -> tuple[Node, float | None, object, Incident | None]:
    """Место и время тревоги: карточка инцидента, прогноз или объект с пикетом."""
    user = request.user
    params = request.query_params
    if incident_id := params.get("incident"):
        incident = get_object_or_404(scope_queryset(Incident.objects.all(), user, "node"), pk=incident_id)
        alert = incident.alerts.exclude(channel=None).select_related("channel").order_by("raised_at").first()
        picket = float(alert.channel.picket) if alert and alert.channel.picket is not None else None
        return incident.node, picket, alert.raised_at if alert else incident.opened_at, incident
    if prediction_id := params.get("prediction"):
        prediction = get_object_or_404(
            scope_queryset(Prediction.objects.select_related("channel"), user, "node"), pk=prediction_id
        )
        channel = prediction.channel
        picket = float(channel.picket) if channel and channel.picket is not None else None
        return prediction.node, picket, prediction.issued_at, None
    node = get_object_or_404(scope_queryset(Node.objects.all(), user, ""), pk=params.get("node"))
    picket = params.get("picket")
    return node, float(picket) if picket else None, None, None


class CameraListView(APIView):
    """Ближайшие к месту тревоги камеры (?incident=, ?prediction= или ?node=&picket=)."""

    permission_classes = [require_perm("assets.view_camera")]

    def get(self, request):
        node, picket, at, _ = _place(request)
        # камеры предка вне зоны пользователя не показываются: кадр по ним он всё равно не получит
        cameras = (
            [c for c in video.nearest(node, picket) if in_scope(request.user, c.node)]
            if video.enabled()
            else []
        )
        return Response(
            {
                "enabled": video.enabled(),
                "mode": registry.BY_CODE["vms"].mode(),
                "alarm_at": at,
                "picket": picket,
                "cameras": [video.describe(c, picket, at) for c in cameras],
            }
        )


class CameraSnapshotView(APIView):
    """
    Кадр камеры на момент (?at=ISO) или текущий. С ?incident= просмотр записывается в хронологию
    карточки: проверка по камерам — часть верификации (ТЗ §12), её видно руководителю и в разборе.
    """

    permission_classes = [require_perm("assets.view_camera")]

    def get(self, request, pk: int):
        import httpx

        camera = get_object_or_404(
            scope_queryset(Camera.objects.select_related("node"), request.user, "node"), pk=pk
        )
        if not video.enabled():
            return Response({"detail": "Видеонаблюдение отключено"}, status=status.HTTP_404_NOT_FOUND)
        at = _moment(request.query_params.get("at"))
        try:
            content, content_type = video.snapshot(camera, at)
        except httpx.HTTPError as exc:
            return Response({"detail": f"Система видеонаблюдения недоступна: {exc}"}, status=502)
        if not content_type.startswith("image/"):
            return Response({"detail": "Система видеонаблюдения вернула не изображение"}, status=502)
        log_action(request, "camera.snapshot", obj=camera, payload={"at": at.isoformat() if at else None})
        if incident_id := request.query_params.get("incident"):
            self._record(request, camera, incident_id, at)
        response = HttpResponse(content, content_type=content_type)
        # кадр может быть SVG (эмулятор): в документе-изображении скрипты не выполняются
        response["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
        response["Cache-Control"] = "private, no-store"
        return response

    def _record(self, request, camera: Camera, incident_id: str, at) -> None:
        incident = scope_queryset(Incident.objects.all(), request.user, "node").filter(pk=incident_id).first()
        if incident is None:
            return
        # повторные обновления кадра той же камеры не засоряют хронологию
        recent = IncidentEvent.objects.filter(
            incident=incident,
            kind=IncidentEvent.Kind.VIDEO_CHECK,
            actor=request.user,
            payload__camera=camera.pk,
            ts__gte=timezone.now() - timedelta(minutes=10),
        )
        if recent.exists():
            return
        when = f" (кадр на {timezone.localtime(at):%d.%m %H:%M})" if at else " (текущий кадр)"
        IncidentEvent.objects.create(
            incident=incident,
            kind=IncidentEvent.Kind.VIDEO_CHECK,
            actor=request.user,
            text=f"Проверка по камере «{camera.name}»{when}",
            payload={"camera": camera.pk, "at": at.isoformat() if at else None},
        )
