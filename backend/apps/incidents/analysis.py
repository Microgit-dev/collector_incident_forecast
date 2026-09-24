"""
Анализ эпизода: тип технического эпизода, гипотезы первопричины, следующие действия
и операционный приоритет. Собирает контекст из БД и вызывает чистые функции domain/*.
"""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db.models import Sum
from django.utils import timezone

from .domain.actions import next_actions
from .domain.correlation import TECHNICAL, Context, Signal, contour, hypotheses, technical_type
from .domain.priority import PriorityInput, priority

MSK = ZoneInfo("Europe/Moscow")
# Масштаб технического эпизода поднимает уровень: потеря связи с десятками каналов — не «одиночный сбой»
SCALE_SEVERITY = [(10, "high"), (3, "medium")]
MAX_SIGNALS = 500  # для гипотез хватает последних сигналов: каскад в тысячи сигналов не нужно читать целиком
TYPE_TITLES = {
    "power": "Потеря питания",
    "communication": "Потеря связи",
    "equipment": "Сбой оборудования",
    "sensor_failure": "Сбой датчиков",
}


def _rank(level: str) -> int:
    return ["low", "medium", "high", "critical"].index(level)


def _signals(incident) -> list[Signal]:
    from apps.forecasting.models import ChannelHealth
    from apps.telemetry.models import ChannelDaily

    alerts = list(incident.alerts.select_related("channel__sensor_type").order_by("-raised_at")[:MAX_SIGNALS])
    channel_ids = {a.channel_id for a in alerts if a.channel_id}
    health = dict(ChannelHealth.objects.filter(channel_id__in=channel_ids).values_list("channel_id", "score"))
    since = (incident.first_signal_at or incident.opened_at) - timedelta(days=90)
    history = dict(
        ChannelDaily.objects.filter(
            channel_id__in=channel_ids,
            day__gte=since.date(),
            day__lt=(incident.first_signal_at or incident.opened_at).date(),
        )
        .values("channel_id")
        .annotate(n=Sum("faults"))
        .values_list("channel_id", "n")
    )
    result = []
    for a in alerts:
        ch = a.channel
        state = a.details.get("state") or ("forecast" if a.source == "forecast" else "")
        if a.type == "communication" and not state:
            state = "silent"
        result.append(
            Signal(
                channel_id=a.channel_id,
                state=state,
                ts=a.raised_at,
                sensor_type=ch.sensor_type.name if ch and ch.sensor_type else "",
                name=ch.name if ch else "",
                picket=float(ch.picket) if ch and ch.picket is not None else None,
                health=health.get(a.channel_id),
                fault_history=history.get(a.channel_id) or 0,
                numeric=a.details.get("numeric"),
            )
        )
    return result


def _context(incident) -> Context:
    from apps.assets.models import Channel
    from apps.workorders.models import WorkOrder

    node = incident.node
    works = WorkOrder.objects.filter(
        node__path__startswith=node.path, status=WorkOrder.Status.IN_PROGRESS
    ).count()
    return Context(
        local_time=(incident.first_signal_at or incident.opened_at).astimezone(MSK),
        works_in_progress=works,
        node_channels=Channel.objects.filter(node=node, is_active=True).count(),
    )


def refresh(incident) -> None:
    """Пересчёт после новых сигналов (без save — сохраняет вызывающий)."""
    signals = _signals(incident)
    if contour(incident.type) == TECHNICAL and not incident.is_forecast and signals:
        kind = technical_type(signals)
        if kind != incident.type:
            incident.type = kind
            from .models import IncidentEvent

            IncidentEvent.objects.create(
                incident=incident,
                kind=IncidentEvent.Kind.TYPE_CHANGED,
                text=f"Тип уточнён: {incident.get_type_display()}",
            )
        for threshold, level in SCALE_SEVERITY:
            if incident.channels_count >= threshold and _rank(level) > _rank(incident.severity):
                incident.severity = level
                break
        if incident.channels_count >= 2:
            incident.title = f"{TYPE_TITLES[kind]}: {incident.node.name} — каналов {incident.channels_count}"[
                :255
            ]
    ranked = [] if incident.is_forecast else hypotheses(incident.type, signals, _context(incident))
    incident.hypotheses = [h.as_dict() for h in ranked]
    done = {a["code"]: a for a in incident.actions if a.get("done")}
    steps = next_actions(incident.type, ranked[0].code if ranked else None, incident.is_forecast)
    incident.actions = [
        done.get(code, {"code": code, "title": title, "done": False, "done_by": None, "done_at": None})
        for code, title in steps
    ]
    scores = [s.health for s in signals if s.health is not None]
    incident.data_confidence = round(sum(scores) / len(scores), 1) if scores else None
    refresh_priority(incident)


def refresh_priority(incident, now=None) -> None:
    incident.priority, incident.priority_factors = priority(
        PriorityInput(
            severity=incident.severity,
            contour=incident.contour,
            criticality=incident.node.criticality,
            health=incident.data_confidence,
            channels=incident.channels_count,
            opened_at=incident.opened_at,
            ack_deadline=incident.ack_deadline,
            escalation_level=incident.escalation_level,
            acknowledged=incident.acknowledged_at is not None,
            probability=incident.probability if incident.is_forecast else None,
            now=now or timezone.now(),
            real_threat=next((h["weight"] for h in incident.hypotheses if h["code"] == incident.type), None),
        )
    )


def refresh_open_priorities(now=None) -> int:
    """Раз в минуту: срочность растёт по мере истечения времени на реакцию — очередь пересортировывается."""
    from .models import Incident

    now = now or timezone.now()
    changed = []
    for incident in Incident.objects.filter(status__in=Incident.OPEN_STATUSES).select_related("node"):
        before = incident.priority
        refresh_priority(incident, now)
        if incident.priority != before:
            changed.append(incident)
    Incident.objects.bulk_update(changed, ["priority", "priority_factors"], batch_size=500)
    return len(changed)
