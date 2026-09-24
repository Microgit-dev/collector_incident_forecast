"""
Главный экран диспетчера: поток «сырые сигналы → эпизоды → требуют действия» за скользящее окно
и активные риски по всем задачам прогноза. Всё в зоне ответственности пользователя.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.forecasting.models import ChannelRisk, Prediction, RiskSnapshot
from apps.incidents.domain.correlation import contour
from apps.incidents.models import Alert, Incident
from apps.topology.selectors import scope_queryset

OPEN = (Incident.Status.NEW, Incident.Status.ACKNOWLEDGED, Incident.Status.IN_PROGRESS)
LEVEL_ORDER = ("critical", "high", "medium", "low")
ML_TASKS = ("sensor_failure", "gas", "flood")
INDICATORS = ("fire", "intrusion")


def _incident_row(i: Incident, now) -> dict:
    return {
        "id": i.pk,
        "title": i.title,
        "type": i.type,
        "severity": i.severity,
        "status": i.status,
        "priority": round(i.priority),
        "contour": i.contour,
        "is_forecast": i.is_forecast,
        "node_name": i.node.name,
        "signals_count": i.signals_count,
        "channels_count": i.channels_count,
        "last_signal_at": i.last_signal_at,
        "ack_deadline": i.ack_deadline,
        "overdue": bool(i.ack_deadline and i.ack_deadline < now and i.status == Incident.Status.NEW),
        "assigned_to_name": i.assigned_to.get_full_name() if i.assigned_to else None,
        "escalation_level": i.escalation_level,
    }


def _latest_predictions(task: str, channel_ids: list[int]) -> dict[int, int]:
    """Последняя запись журнала по каналу — на неё ведёт ссылка «карточка прогноза»."""
    latest: dict[int, int] = {}
    for channel_id, pk in (
        Prediction.objects.filter(task=task, channel_id__in=channel_ids, is_backtest=False)
        .order_by("-issued_at")
        .values_list("channel_id", "pk")[:200]
    ):
        latest.setdefault(channel_id, pk)
    return latest


def stream(user, minutes: int) -> dict:
    """Сигналы за окно, во что они склеились и что ждёт решения."""
    now = timezone.now()
    since = now - timedelta(minutes=minutes)
    alerts = scope_queryset(Alert.objects.exclude(source=Alert.Source.FORECAST), user, "node")
    window = alerts.filter(raised_at__gte=since)
    by_type = dict(window.order_by().values_list("type").annotate(n=Count("pk")))
    by_contour = Counter()
    for kind, n in by_type.items():
        by_contour[contour(kind)] += n
    bucket = 1 if minutes <= 60 else 10 if minutes <= 360 else 60
    series = Counter()
    for ts, kind in window.values_list("raised_at", "type"):
        local = timezone.localtime(ts)
        minute = local.minute - local.minute % bucket if bucket < 60 else 0
        slot = local.replace(minute=minute, second=0, microsecond=0)
        series[(slot, contour(kind))] += 1
    slots = sorted({s for s, _ in series})

    incidents = scope_queryset(Incident.objects.select_related("node", "assigned_to"), user, "node")
    touched = incidents.filter(last_signal_at__gte=since)
    open_qs = incidents.filter(status__in=OPEN)
    need = open_qs.filter(Q(status=Incident.Status.NEW) | Q(assigned_to=None)).order_by("-priority")
    return {
        "now": now,
        "minutes": minutes,
        "last_signal_at": alerts.aggregate(t=Max("raised_at"))["t"],
        "signals": {
            "total": sum(by_type.values()),
            "by_contour": dict(by_contour),
            "by_type": by_type,
            "bucket_minutes": bucket,
            "series": [
                {"t": s, "physical": series[(s, "physical")], "technical": series[(s, "technical")]}
                for s in slots
            ],
        },
        "episodes": {
            "touched": touched.count(),
            "new": touched.filter(opened_at__gte=since).count(),
            "items": [_incident_row(i, now) for i in touched.order_by("-priority")[:6]],
        },
        "action": {
            "open": open_qs.count(),
            "unassigned": need.count(),
            "overdue": need.filter(status=Incident.Status.NEW, ack_deadline__lt=now).count(),
            "escalated": open_qs.filter(escalation_level__gt=0).count(),
            "items": [_incident_row(i, now) for i in need[:10]],
        },
    }


def active_risks(user) -> dict:
    """Текущие риски: по моделям — последний расчёт по каналам, по индикаторам — последние записи журнала."""
    tasks = {}
    risks = scope_queryset(ChannelRisk.objects.all(), user, "channel__node")
    for task in ML_TASKS:
        qs = risks.filter(task=task)
        levels = dict(qs.order_by().values_list("risk_level").annotate(n=Count("pk")))
        top = (
            qs.filter(risk_level__in=("critical", "high"))
            .select_related("channel__node")
            .order_by("-probability")[:5]
        )
        journal = _latest_predictions(task, [r.channel_id for r in top])
        tasks[task] = {
            "as_of": qs.aggregate(t=Max("as_of"))["t"],
            "levels": {lvl: levels.get(lvl, 0) for lvl in LEVEL_ORDER if lvl != "low"},
            "top": [
                {
                    "channel": r.channel_id,
                    "prediction": journal.get(r.channel_id),
                    "channel_name": r.channel.name,
                    "node_name": r.channel.node.name,
                    "probability": round(r.probability, 3),
                    "risk_level": r.risk_level,
                    "factor": r.factors[0]["title"] if r.factors else "",
                }
                for r in top
            ],
        }
    predictions = scope_queryset(Prediction.objects.filter(is_backtest=False), user, "node")
    for task in INDICATORS:
        qs = predictions.filter(task=task)
        last = qs.aggregate(t=Max("issued_at"))["t"]
        # Индикатор пересчитывается циклом; «активные» — записи последних суток расчётов
        recent = qs.filter(issued_at__gte=last - timedelta(hours=24)) if last else qs.none()
        levels = dict(recent.order_by().values_list("risk_level").annotate(n=Count("pk")))
        tasks[task] = {
            "as_of": last,
            "levels": {lvl: levels.get(lvl, 0) for lvl in LEVEL_ORDER if lvl != "low"},
            "top": [
                {
                    "prediction": p.pk,
                    "node_name": p.node.name,
                    "probability": round(p.probability, 3),
                    "risk_level": p.risk_level,
                    "factor": p.factors[0]["title"] if p.factors else "",
                    "issued_at": p.issued_at,
                }
                for p in recent.select_related("node").order_by("-probability")[:5]
            ],
        }
    nodes = scope_queryset(RiskSnapshot.objects.all(), user, "node")
    latest = Q(pk__in=[])
    for task, last in nodes.order_by().values_list("task").annotate(t=Max("as_of")):
        latest |= Q(task=task, as_of=last)
    hot = (
        nodes.filter(latest, risk_level__in=("critical", "high"))
        .select_related("node")
        .order_by("-max_probability")
    )
    return {
        "tasks": tasks,
        "nodes": [
            {
                "node": s.node_id,
                "node_name": s.node.name,
                "task": s.task,
                "risk_level": s.risk_level,
                "max_probability": round(s.max_probability, 3),
                "channels_at_risk": s.channels_at_risk,
            }
            for s in hot[:10]
        ],
    }
