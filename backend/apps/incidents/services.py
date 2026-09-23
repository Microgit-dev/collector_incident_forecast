"""
Жизненный цикл инцидента и вертикаль управления.

Ответственный уровень (responsible_node) — ближайший вверх по дереву узел, за которым
закреплены люди. Если на инцидент не отреагировали за время из EscalationPolicy,
ответственность поднимается к следующему укомплектованному узлу (участок → объект → район),
и уведомление получает следующий уровень руководства. Диспетчеры ОДС с глобальной зоной
видят и получают всё.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.forecasting.models import Prediction, RiskLevel
from apps.notifications.services import notify
from apps.topology.models import Node

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

# Сигналы одного типа по одному объекту в этом окне склеиваются в один инцидент
GROUPING_WINDOW = timedelta(minutes=30)
SEVERITY_ORDER = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
DEFAULT_ACK_MINUTES = {RiskLevel.LOW: 240, RiskLevel.MEDIUM: 60, RiskLevel.HIGH: 15, RiskLevel.CRITICAL: 5}


class IncidentError(Exception):
    """Нарушение бизнес-правила; API отдаёт его как 409/400 с текстом."""


# ---------- кто отвечает ----------


def _users_with_scope(node: Node):
    return User.objects.filter(is_active=True, scope_node=node)


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


@transaction.atomic
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
    raised_at = raised_at or timezone.now()
    incident = (
        Incident.objects.select_for_update()
        .filter(
            node=node,
            type=type,
            status__in=Incident.OPEN_STATUSES,
            opened_at__gte=raised_at - GROUPING_WINDOW,
        )
        .order_by("-opened_at")
        .first()
    )
    created = incident is None
    if created:
        incident = Incident.objects.create(
            type=type,
            severity=severity,
            node=node,
            responsible_node=first_staffed_node(node),
            title=title,
            opened_at=raised_at,
            ack_deadline=_ack_deadline(severity, raised_at),
            is_forecast=source == Alert.Source.FORECAST,
            probability=probability,
            horizon_hours=horizon_hours,
        )
        _event(incident, IncidentEvent.Kind.OPENED, text=title)
    elif SEVERITY_ORDER.index(severity) > SEVERITY_ORDER.index(incident.severity):
        incident.severity = severity
        incident.save(update_fields=["severity", "updated_at"])

    alert = Alert.objects.create(
        incident=incident,
        source=source,
        type=type,
        severity=severity,
        node=node,
        channel=channel,
        prediction=prediction,
        raised_at=raised_at,
        title=title,
        details=details or {},
    )
    if not created:
        _event(incident, IncidentEvent.Kind.ALERT_ATTACHED, text=title, alert_id=alert.pk)
    _notify(incident, title if created else f"Новый сигнал: {title}")
    return alert


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
