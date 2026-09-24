"""
Жизненный цикл инцидента и вертикаль управления.

Ответственный уровень (responsible_node) — ближайший вверх по дереву узел, за которым
закреплены люди. Если на инцидент не отреагировали за время из EscalationPolicy,
ответственность поднимается к следующему укомплектованному узлу (участок → объект → район),
и уведомление получает следующий уровень руководства. Диспетчеры ОДС с глобальной зоной
видят и получают всё.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.forecasting.models import Prediction, RiskLevel
from apps.notifications.services import notify
from apps.topology.models import Node

from . import analysis
from .domain.correlation import PHYSICAL, contour
from .models import (
    Alert,
    Decision,
    DecisionOutcome,
    DecisionReason,
    EscalationPolicy,
    Incident,
    IncidentEvent,
)

User = get_user_model()

# Сигнал присоединяется к эпизоду, если с последнего сигнала эпизода прошло не больше окна
GROUPING_WINDOW = timedelta(minutes=30)
SEVERITY_ORDER = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
DEFAULT_ACK_MINUTES = {RiskLevel.LOW: 240, RiskLevel.MEDIUM: 60, RiskLevel.HIGH: 15, RiskLevel.CRITICAL: 5}


class IncidentError(Exception):
    """Нарушение бизнес-правила; API отдаёт его как 409/400 с текстом."""


# ---------- кто отвечает ----------


def _users_with_scope(node: Node):
    """Кто на этом узле принимает тревоги: бригады и наблюдатели в зоне не считаются дежурной сменой."""
    handles = Q(groups__permissions__codename="acknowledge_alert") | Q(
        user_permissions__codename="acknowledge_alert"
    )
    return (
        User.objects.filter(is_active=True, scope_node=node).filter(handles | Q(is_superuser=True)).distinct()
    )


def global_scope_users():
    return (
        User.objects.filter(is_active=True)
        .filter(
            Q(user_permissions__codename="view_all_scopes")
            | Q(groups__permissions__codename="view_all_scopes")
        )
        .distinct()
    )


def first_staffed_node(node: Node) -> Node:
    """Ближайший вверх по дереву узел, где есть люди; корень — если нигде нет."""
    for candidate in [node, *reversed(Node.objects.get_ancestors(node))]:
        if _users_with_scope(candidate).exists():
            return candidate
    return Node.objects.get_root(node)


def recipients(incident: Incident) -> list:
    users = {u.pk: u for u in _users_with_scope(incident.responsible_node)}
    users.update({u.pk: u for u in global_scope_users()})
    return list(users.values())


def _ack_deadline(severity: str, start: datetime) -> datetime:
    policy = EscalationPolicy.objects.filter(severity=severity).first()
    minutes = policy.ack_timeout_minutes if policy else DEFAULT_ACK_MINUTES[severity]
    return start + timedelta(minutes=minutes)


def _event(incident: Incident, kind: str, actor=None, text: str = "", **payload) -> None:
    IncidentEvent.objects.create(incident=incident, kind=kind, actor=actor, text=text[:512], payload=payload)


def _notify(incident: Incident, text: str) -> None:
    transaction.on_commit(
        lambda: notify(
            recipients(incident),
            title=f"{incident.get_severity_display()}: {incident.title}",
            body=text,
            level=incident.severity,
            link=f"/incidents/{incident.pk}",
            payload={"incident_id": incident.pk, "type": incident.type},
        )
    )


# ---------- жизненный цикл ----------


@dataclass(frozen=True, slots=True)
class SignalIn:
    """Сигнал на входе: смена состояния канала, прогноз выше порога, молчание."""

    title: str
    severity: str
    ts: datetime
    channel: object | None = None
    state: str = ""
    details: dict = field(default_factory=dict)
    prediction: Prediction | None = None
    probability: float | None = None
    horizon_hours: int | None = None


def _grouping_filter(node: Node, incident_type: str, is_forecast: bool) -> Q:
    """Физические угрозы и прогнозы склеиваются внутри своего типа, технические — в один эпизод объекта."""
    q = Q(
        node=node, is_forecast=is_forecast, contour=contour(incident_type), status__in=Incident.OPEN_STATUSES
    )
    if contour(incident_type) == PHYSICAL or is_forecast:
        q &= Q(type=incident_type)
    return q


@transaction.atomic
def register_signals(*, type: str, node: Node, source: str, signals: list[SignalIn]) -> list[Alert]:
    """
    Сигналы → эпизод. Сигнал склеивается с открытой карточкой того же объекта и контура,
    если с её последнего сигнала прошло не больше GROUPING_WINDOW (окно скользит: каскад,
    идущий часами, остаётся одной карточкой). Уведомление — только при открытии карточки,
    росте уровня или уточнении типа, а не на каждый сигнал.
    """
    if not signals:
        return []
    signals = sorted(signals, key=lambda x: x.ts)
    first, last = signals[0], signals[-1]
    is_forecast = source == Alert.Source.FORECAST
    severity = max((x.severity for x in signals), key=SEVERITY_ORDER.index)
    incident = (
        Incident.objects.select_for_update()
        .filter(_grouping_filter(node, type, is_forecast), last_signal_at__gte=first.ts - GROUPING_WINDOW)
        .order_by("-last_signal_at")
        .first()
    )
    created = incident is None
    bumped = False
    if created:
        incident = Incident.objects.create(
            type=type,
            contour=contour(type),
            severity=severity,
            node=node,
            responsible_node=first_staffed_node(node),
            title=first.title,
            opened_at=first.ts,
            first_signal_at=first.ts,
            last_signal_at=last.ts,
            ack_deadline=_ack_deadline(severity, first.ts),
            is_forecast=is_forecast,
            probability=first.probability,
            horizon_hours=first.horizon_hours,
        )
        _event(incident, IncidentEvent.Kind.OPENED, text=first.title)
    elif SEVERITY_ORDER.index(severity) > SEVERITY_ORDER.index(incident.severity):
        incident.severity, bumped = severity, True

    alerts = Alert.objects.bulk_create(
        [
            Alert(
                incident=incident,
                source=source,
                type=type,
                severity=x.severity,
                node=node,
                channel=x.channel,
                prediction=x.prediction,
                raised_at=x.ts,
                title=x.title[:255],
                details={"state": x.state, **x.details} if x.state else x.details,
            )
            for x in signals
        ]
    )
    incident.signals_count = incident.alerts.count()
    incident.channels_count = incident.alerts.exclude(channel=None).values("channel").distinct().count()
    incident.first_signal_at = min(incident.first_signal_at or first.ts, first.ts)
    incident.last_signal_at = max(incident.last_signal_at or last.ts, last.ts)
    if is_forecast and first.probability is not None:
        incident.probability = max(incident.probability or 0, max(x.probability or 0 for x in signals))
    if not created:
        text = last.title if len(signals) == 1 else f"Добавлено сигналов: {len(signals)}"
        _event(incident, IncidentEvent.Kind.ALERT_ATTACHED, text=text, alerts=len(signals))

    previous_type, previous_severity = incident.type, incident.severity
    analysis.refresh(incident)
    if SEVERITY_ORDER.index(incident.severity) > SEVERITY_ORDER.index(previous_severity):
        bumped = True
        tighter = _ack_deadline(incident.severity, last.ts)
        incident.ack_deadline = min(incident.ack_deadline, tighter) if incident.ack_deadline else tighter
    incident.save()
    if created:
        _notify(incident, incident.title)
    elif bumped or incident.type != previous_type:
        _notify(
            incident,
            f"Уточнено: {incident.get_type_display()}, {incident.get_severity_display().lower()} уровень",
        )
    return alerts


def raise_alert(
    *,
    type: str,
    severity: str,
    node: Node,
    title: str,
    source: str,
    channel=None,
    prediction: Prediction | None = None,
    details: dict | None = None,
    raised_at: datetime | None = None,
    probability: float | None = None,
    horizon_hours: int | None = None,
) -> Alert:
    """Один сигнал (прогноз, молчание, ручной ввод) — частный случай register_signals."""
    signal = SignalIn(
        title=title,
        severity=severity,
        ts=raised_at or timezone.now(),
        channel=channel,
        state=(details or {}).get("state", ""),
        details={k: v for k, v in (details or {}).items() if k != "state"},
        prediction=prediction,
        probability=probability,
        horizon_hours=horizon_hours,
    )
    return register_signals(type=type, node=node, source=source, signals=[signal])[0]


@transaction.atomic
def mark_action(incident: Incident, user, code: str, done: bool = True) -> Incident:
    """Отметка шага чек-листа «что делать»; попадает в хронологию карточки."""
    incident = Incident.objects.select_for_update().get(pk=incident.pk)
    for step in incident.actions:
        if step["code"] == code:
            step["done"] = done
            step["done_by"] = (user.get_full_name() or user.get_username()) if done else None
            step["done_at"] = timezone.now().isoformat() if done else None
            if done:
                _event(incident, IncidentEvent.Kind.ACTION_DONE, actor=user, text=step["title"])
            break
    else:
        raise IncidentError("Нет такого шага")
    incident.save(update_fields=["actions", "updated_at"])
    return incident


@transaction.atomic
def acknowledge(incident: Incident, user) -> Incident:
    incident = Incident.objects.select_for_update().get(pk=incident.pk)
    if incident.status != Incident.Status.NEW:
        return incident
    now = timezone.now()
    incident.status, incident.acknowledged_at = Incident.Status.ACKNOWLEDGED, now
    incident.save(update_fields=["status", "acknowledged_at", "updated_at"])
    incident.alerts.filter(acknowledged_at=None).update(acknowledged_by=user, acknowledged_at=now)
    _event(incident, IncidentEvent.Kind.ACKNOWLEDGED, actor=user)
    return incident


@transaction.atomic
def take(incident: Incident, user, *, force: bool = False) -> Incident:
    """Закрепить карточку за собой. Второй диспетчер получает отказ, если нет права takeover."""
    incident = Incident.objects.select_for_update().get(pk=incident.pk)
    locked_by_other = incident.assigned_to_id and incident.assigned_to_id != user.pk
    if locked_by_other and not (force and user.has_perm("incidents.takeover_incident")):
        raise IncidentError(
            f"Инцидент уже в работе у {incident.assigned_to.get_full_name() or incident.assigned_to}"
        )
    if incident.status == Incident.Status.NEW:
        incident.acknowledged_at = timezone.now()
    incident.assigned_to = user
    incident.status = Incident.Status.IN_PROGRESS
    incident.save(update_fields=["assigned_to", "status", "acknowledged_at", "updated_at"])
    _event(incident, IncidentEvent.Kind.ASSIGNED, actor=user)
    return incident


@transaction.atomic
def release(incident: Incident, user) -> Incident:
    incident = Incident.objects.select_for_update().get(pk=incident.pk)
    if incident.assigned_to_id != user.pk:
        raise IncidentError("Освободить можно только свой инцидент")
    incident.assigned_to = None
    incident.save(update_fields=["assigned_to", "updated_at"])
    _event(incident, IncidentEvent.Kind.RELEASED, actor=user)
    return incident


_OUTCOME_STATUS = {
    DecisionOutcome.FALSE_ALARM: Incident.Status.RESOLVED,
    DecisionOutcome.RESOLVED: Incident.Status.RESOLVED,
    DecisionOutcome.BRIGADE_DISPATCHED: Incident.Status.IN_PROGRESS,
    DecisionOutcome.CHECK_REQUESTED: Incident.Status.IN_PROGRESS,
    DecisionOutcome.CONFIRMED: Incident.Status.IN_PROGRESS,
    DecisionOutcome.MONITORING: Incident.Status.ACKNOWLEDGED,
}
_OUTCOME_PREDICTION = {
    DecisionOutcome.FALSE_ALARM: Prediction.Outcome.NOT_CONFIRMED,
    DecisionOutcome.CONFIRMED: Prediction.Outcome.CONFIRMED,
    DecisionOutcome.BRIGADE_DISPATCHED: Prediction.Outcome.CONFIRMED,
    DecisionOutcome.RESOLVED: Prediction.Outcome.PREVENTED,
}


@transaction.atomic
def decide(
    incident: Incident, user, *, outcome: str, reason: DecisionReason | None = None, comment: str = ""
) -> Decision:
    """Решение диспетчера: меняет статус, размечает связанные прогнозы (обратная связь для дообучения)."""
    incident = Incident.objects.select_for_update().get(pk=incident.pk)
    if incident.status == Incident.Status.CLOSED:
        raise IncidentError("Инцидент закрыт")
    if (
        incident.assigned_to_id
        and incident.assigned_to_id != user.pk
        and not user.has_perm("incidents.takeover_incident")
    ):
        raise IncidentError("Инцидент в работе у другого диспетчера")
    if reason and reason.outcome != outcome:
        raise IncidentError("Причина не соответствует виду решения")

    decision = Decision.objects.create(
        incident=incident, outcome=outcome, reason=reason, comment=comment, decided_by=user
    )
    now = timezone.now()
    incident.status = _OUTCOME_STATUS[outcome]
    incident.acknowledged_at = incident.acknowledged_at or now
    if incident.status == Incident.Status.RESOLVED:
        incident.resolved_at = now
    incident.save(update_fields=["status", "acknowledged_at", "resolved_at", "updated_at"])

    if outcome in _OUTCOME_PREDICTION:
        Prediction.objects.filter(alerts__incident=incident, outcome=Prediction.Outcome.PENDING).update(
            outcome=_OUTCOME_PREDICTION[outcome], outcome_at=now
        )
    _event(
        incident,
        IncidentEvent.Kind.DECISION,
        actor=user,
        text=f"{decision.get_outcome_display()}{': ' + reason.name if reason else ''}",
        decision_id=decision.pk,
    )
    return decision


@transaction.atomic
def escalate(incident: Incident, *, actor=None, reason: str = "timeout") -> Incident:
    incident = Incident.objects.select_for_update().select_related("responsible_node").get(pk=incident.pk)
    policy = EscalationPolicy.objects.filter(severity=incident.severity).first()
    max_level = policy.max_level if policy else 3
    parent = Node.objects.get_parent(incident.responsible_node)
    if parent is None or incident.escalation_level >= max_level:
        return incident
    now = timezone.now()
    incident.responsible_node = first_staffed_node(parent)
    incident.escalation_level += 1
    incident.ack_deadline = _ack_deadline(incident.severity, now)
    incident.save(update_fields=["responsible_node", "escalation_level", "ack_deadline", "updated_at"])
    text = f"Эскалация на уровень «{incident.responsible_node.name}» ({'нет реакции' if reason == 'timeout' else reason})"
    _event(incident, IncidentEvent.Kind.ESCALATED, actor=actor, text=text, level=incident.escalation_level)
    _notify(incident, text)
    return incident


def escalate_overdue(now: datetime | None = None) -> int:
    now = now or timezone.now()
    overdue = Incident.objects.filter(status=Incident.Status.NEW, ack_deadline__lt=now).values_list(
        "pk", flat=True
    )
    count = 0
    for pk in overdue:
        escalate(Incident(pk=pk))
        count += 1
    return count
