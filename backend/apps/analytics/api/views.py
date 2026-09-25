from datetime import timedelta

from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import require_perm

from ..cache import cached
from ..flood import flood_reduction
from ..models import ReportExport
from ..selectors import overview


class OverviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(overview(request.user))


class WorkspaceView(APIView):
    """Рабочее место роли: счётчики, списки и слой схемы; ?role= — другая роль пользователя."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from ..workspace import workspace

        return Response(workspace(request.user, request.query_params.get("role")))


class LiveView(APIView):
    """Главный экран: сигналы за окно → эпизоды → требуют действия, активные риски."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from apps.forecasting.data import data_clock

        from ..live import active_risks, stream

        minutes = min(max(int(request.query_params.get("minutes", 10)), 1), 24 * 60)
        # поток — всегда свежий; риски и время данных пересчитываются не чаще раза в минуту
        risks = cached(
            "risks", request.user, (), lambda: {"risks": active_risks(request.user), "clock": data_clock()}
        )
        return Response(
            stream(request.user, minutes) | {"risks": risks["risks"], "data_clock": risks["clock"]}
        )


class SchemeView(APIView):
    """Линейная схема коллекторов по пикетам: GeoJSON в схематических координатах, ?geometry=wkt — WKT."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from ..scheme import scheme

        params = request.query_params
        try:
            complex_id = int(params["complex"]) if params.get("complex") else None
            bin_size = int(params["bin"]) if params.get("bin") else None
        except ValueError:
            return Response({"detail": "Неверные параметры"}, status=400)
        task = params.get("task") or None
        result = cached(
            "scheme",
            request.user,
            (complex_id, task, bin_size),
            lambda: scheme(request.user, complex_id=complex_id, task=task, bin_size=bin_size),
        )
        if params.get("workorders") in ("1", "true"):
            from ..scheme import workorders_layer

            # слой заявок — по пользователю, поверх общей для зоны и ролей схемы из кеша
            result = {**result, "features": result["features"] + workorders_layer(request.user, result)}
        if params.get("geometry") == "wkt":
            from ..scheme import to_wkt

            # копия: объект из кеша не меняем
            result = {
                **result,
                "features": [f | {"geometry": to_wkt(f["geometry"])} for f in result["features"]],
            }
        return Response(result)


class FloodView(APIView):
    """Снижение нагрузки: сигналы потока → эпизоды за период до «времени данных»."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from apps.forecasting.data import data_clock

        end = data_clock()
        if end is None:
            return Response({"signals": 0, "episodes": 0, "factor": None})
        days = min(max(int(request.query_params.get("days", 30)), 1), 30)
        return Response(flood_reduction(end, days))


def _history_period(request):
    from datetime import date

    from ..history import period

    return period(
        date.fromisoformat(request.query_params["from"]), date.fromisoformat(request.query_params["to"])
    )


class HistoryChannelView(APIView):
    """Режим просмотра истории: канал за период (сырые показания до месяца, дальше — по суткам)."""

    permission_classes = [require_perm("telemetry.view_channeldaily")]

    def get(self, request):
        from django.shortcuts import get_object_or_404

        from apps.assets.models import Channel
        from apps.audit.services import log_action
        from apps.topology.selectors import scope_queryset

        from ..history import HistoryError, channel_history

        channel = get_object_or_404(
            scope_queryset(
                Channel.objects.select_related("node", "sensor_type__profile", "profile_override"),
                request.user,
                "node",
            ),
            pk=request.query_params.get("channel"),
        )
        try:
            start, end = _history_period(request)
        except (KeyError, ValueError, HistoryError) as exc:
            return Response({"detail": f"Неверный период: {exc}"}, status=400)
        log_action(
            request,
            "history.channel",
            obj=channel,
            payload={"from": start.isoformat(), "to": end.isoformat()},
        )
        return Response(channel_history(channel, start, end))


class HistoryNodeView(APIView):
    """Режим просмотра истории: объект за период — каналы × сутки по худшему состоянию, карточки."""

    permission_classes = [require_perm("telemetry.view_channeldaily")]

    def get(self, request):
        from django.shortcuts import get_object_or_404

        from apps.topology.models import Node
        from apps.topology.selectors import scope_queryset

        from ..history import HistoryError, node_history

        node = get_object_or_404(
            scope_queryset(Node.objects.all(), request.user, ""), pk=request.query_params.get("node")
        )
        try:
            start, end = _history_period(request)
        except (KeyError, ValueError, HistoryError) as exc:
            return Response({"detail": f"Неверный период: {exc}"}, status=400)
        if end - start > timedelta(days=366):
            return Response({"detail": "Для объекта период — не больше года"}, status=400)
        return Response(node_history(node, start, end))


class HistoryCoverageView(APIView):
    permission_classes = [require_perm("telemetry.view_channeldaily")]

    def get(self, request):
        from ..history import coverage

        return Response(cached("history-coverage", request.user, (), coverage, ttl=600))


class ReplayView(APIView):
    """Разбор исторического эпизода: объект и интервал до 24 часов."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from datetime import datetime

        from django.shortcuts import get_object_or_404

        from apps.audit.services import log_action
        from apps.topology.models import Node
        from apps.topology.selectors import scope_queryset

        from ..replay import ReplayError, replay

        node = get_object_or_404(
            scope_queryset(Node.objects.all(), request.user, ""), pk=request.query_params.get("node")
        )
        try:
            start = datetime.fromisoformat(request.query_params["from"])
            end = datetime.fromisoformat(request.query_params["to"])
            result = replay(node, start, end)
        except (KeyError, ValueError) as exc:
            return Response({"detail": f"Неверные параметры: {exc}"}, status=400)
        except ReplayError as exc:
            return Response({"detail": str(exc)}, status=400)
        log_action(
            request, "analytics.replay", obj=node, payload={"from": start.isoformat(), "to": end.isoformat()}
        )
        return Response(result)


def _period(request):
    """Период из ?from=YYYY-MM-DD&to=YYYY-MM-DD (включительно, по Москве); по умолчанию — 30 суток."""
    from datetime import date, datetime, time
    from zoneinfo import ZoneInfo

    from ..efficiency import default_period

    msk = ZoneInfo("Europe/Moscow")
    params = request.query_params if request.method == "GET" else request.data
    if params.get("from") and params.get("to"):
        start = datetime.combine(date.fromisoformat(params["from"]), time(), msk)
        end = datetime.combine(date.fromisoformat(params["to"]), time(), msk) + timedelta(days=1)
        if end <= start or end - start > timedelta(days=366):
            raise ValueError("Период — от суток до года")
        return start, end
    return default_period(request.user)


def _flag(request, name: str, default: bool) -> bool:
    params = request.query_params if request.method == "GET" else request.data
    value = params.get(name)
    return default if value in (None, "") else str(value).lower() in ("1", "true", "yes")


class EfficiencyView(APIView):
    """Эффективность диспетчеров за период (ТЗ §8)."""

    permission_classes = [require_perm("analytics.view_reportexport")]

    def get(self, request):
        from ..efficiency import efficiency

        try:
            since, until = _period(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(efficiency(request.user, since, until, _flag(request, "include_emulated", True)))


class StaffView(APIView):
    """Сотрудники и команды за период: отклик первым, гонки, качество решений, нагрузка, обучение."""

    permission_classes = [require_perm("analytics.view_reportexport")]

    def get(self, request):
        from ..staff import staff_metrics

        try:
            since, until = _period(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(staff_metrics(request.user, since, until, _flag(request, "include_emulated", True)))


class MyMetricsView(APIView):
    """Мои показатели: своя строка, медиана коллег зоны, место в рейтинге «кто первый»."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from ..staff import my_metrics, my_period

        try:
            own = None if request.query_params.get("from") else my_period(request.user)
            since, until = own or _period(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(my_metrics(request.user, since, until))


class QualityView(APIView):
    """Качество прогнозов за период (ТЗ §9)."""

    permission_classes = [require_perm("analytics.view_reportexport")]

    def get(self, request):
        from ..quality import quality

        try:
            since, until = _period(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(quality(request.user, since, until, _flag(request, "backtest", False)))


class RangesView(APIView):
    """Какие периоды есть в данных: реальная работа, эмуляция смен, оперативный журнал, бэктест."""

    permission_classes = [require_perm("analytics.view_reportexport")]

    def get(self, request):
        from django.db.models import Count, Max, Min

        from apps.forecasting.models import Prediction
        from apps.incidents.models import Incident
        from apps.topology.selectors import scope_queryset

        def span(qs, field):
            row = qs.aggregate(a=Min(field), b=Max(field), n=Count("pk"))
            return {"from": row["a"], "to": row["b"], "count": row["n"]} if row["n"] else None

        incidents = scope_queryset(Incident.objects.all(), request.user, "node")
        journal = scope_queryset(Prediction.objects.all(), request.user, "node")
        return Response(
            {
                "live": span(incidents.filter(is_emulated=False), "opened_at"),
                "emulated": span(incidents.filter(is_emulated=True), "opened_at"),
                "journal": span(journal.filter(is_backtest=False), "issued_at"),
                "backtest": span(journal.filter(is_backtest=True), "issued_at"),
            }
        )


class ReportSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.get_full_name", default=None, read_only=True)
    size = serializers.SerializerMethodField()

    class Meta:
        model = ReportExport
        fields = ("id", "kind", "format", "params", "created_by_name", "created_at", "size")

    def get_size(self, obj):
        try:
            return obj.file.size
        except (OSError, ValueError):
            return None


class ReportViewSet(viewsets.ReadOnlyModelViewSet):
    """Отчёты PDF/XLSX за период: сформировать, список, скачать. Каждый видит свои отчёты."""

    serializer_class = ReportSerializer
    permission_classes = [require_perm("analytics.view_reportexport")]

    def get_queryset(self):
        return ReportExport.objects.filter(created_by=self.request.user).select_related("created_by")

    def get_permissions(self):
        if self.action == "create":
            return [require_perm("analytics.export_report")()]
        return super().get_permissions()

    def create(self, request):
        from django.core.files.base import ContentFile

        from apps.audit.services import log_action

        from ..reports import collect, to_pdf, to_xlsx

        fmt = request.data.get("format", "pdf")
        if fmt not in ("pdf", "xlsx"):
            return Response({"detail": "Формат — pdf или xlsx"}, status=400)
        try:
            since, until = _period(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        include_emulated = _flag(request, "include_emulated", False)
        backtest = _flag(request, "backtest", False)
        data = collect(request.user, since, until, include_emulated, backtest)
        content = to_pdf(data) if fmt == "pdf" else to_xlsx(data, request.user)
        from zoneinfo import ZoneInfo

        msk = ZoneInfo("Europe/Moscow")
        params = {
            "from": since.astimezone(msk).date().isoformat(),
            "to": (until - timedelta(seconds=1)).astimezone(msk).date().isoformat(),
            "include_emulated": include_emulated,
            "backtest": backtest,
            "scope": data["scope"],
        }
        report = ReportExport(kind="period", format=fmt, params=params, created_by=request.user)
        report.file.save(f"report_{params['from']}_{params['to']}.{fmt}", ContentFile(content), save=True)
        log_action(request, "analytics.report", obj=report, payload=params)
        return Response(ReportSerializer(report).data, status=201)

    @action(detail=True)
    def download(self, request, pk=None):
        from django.http import FileResponse

        report = self.get_object()
        name = f"Отчёт {report.params.get('from')} — {report.params.get('to')}.{report.format}"
        return FileResponse(report.file.open("rb"), as_attachment=True, filename=name)
