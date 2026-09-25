from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.incidents.models import Incident, IncidentEvent, IncidentType

from .models import WorkOrder, WorkType


class WorkOrderError(Exception):
    pass


_INCIDENT_WORK = {
    IncidentType.SENSOR_FAILURE: WorkType.SENSOR_REPLACEMENT,
    IncidentType.POWER: WorkType.POWER_CHECK,
    IncidentType.FLOOD: WorkType.PUMP_SERVICE,
    IncidentType.GAS: WorkType.VENTILATION,
    IncidentType.FIRE: WorkType.INSPECTION,
    IncidentType.INTRUSION: WorkType.SECURITY,
    IncidentType.EQUIPMENT: WorkType.INSPECTION,
}
_DUE_BY_PRIORITY = {
    "critical": timedelta(hours=2),
    "high": timedelta(hours=8),
    "medium": timedelta(days=1),
    "low": timedelta(days=3),
}


def next_number() -> str:
    today = timezone.localdate()
    seq = WorkOrder.objects.filter(created_at__date=today).count() + 1
    return f"ЗН-{today:%Y%m%d}-{seq:04d}"


@transaction.atomic
def draft_from_incident(incident: Incident, user) -> WorkOrder:
    """Черновик заявки по инциденту: вид работ, приоритет и срок подставляются автоматически."""
    now = timezone.now()
    order = WorkOrder.objects.create(
        number=next_number(),
        node=incident.node,
        incident=incident,
        work_type=_INCIDENT_WORK.get(incident.type, WorkType.INSPECTION),
        priority=incident.severity,
        title=f"{incident.get_type_display()} — {incident.node.name}",
        description=(
            f"Основание: инцидент #{incident.pk} «{incident.title}».\n"
            + (
                f"Прогноз: вероятность {incident.probability:.0%} на {incident.horizon_hours} ч.\n"
                if incident.probability
                else ""
            )
        ),
        due_at=now + _DUE_BY_PRIORITY.get(incident.severity, timedelta(days=1)),
        created_by=user,
    )
    IncidentEvent.objects.create(
        incident=incident,
        kind=IncidentEvent.Kind.WORKORDER,
        actor=user,
        text=f"Создан черновик заявки {order.number}",
        payload={"workorder_id": order.pk},
    )
    return order


@transaction.atomic
def draft_from_recommendation(rec, user) -> WorkOrder:
    """Черновик заявки из рекомендации по ТО; рекомендация становится принятой."""
    from datetime import datetime, time

    from .models import MaintenanceRecommendation

    order = WorkOrder.objects.create(
        number=next_number(),
        node=rec.node,
        recommendation=rec,
        equipment=rec.equipment,
        work_type=rec.work_type,
        priority=rec.priority,
        title=f"{rec.get_work_type_display()} — {rec.node.name}",
        description=f"Основание: рекомендация по ТО #{rec.pk}.\n{rec.rationale}",
        due_at=timezone.make_aware(datetime.combine(rec.due_date, time(18, 0))),
        created_by=user,
    )
    rec.status = MaintenanceRecommendation.Status.ACCEPTED
    rec.save(update_fields=["status", "updated_at"])
    return order


_TRANSITIONS = {
    WorkOrder.Status.DRAFT: {WorkOrder.Status.APPROVED, WorkOrder.Status.CANCELLED},
    WorkOrder.Status.APPROVED: {WorkOrder.Status.SUBMITTED, WorkOrder.Status.CANCELLED},
    WorkOrder.Status.SUBMITTED: {WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.CANCELLED},
    WorkOrder.Status.IN_PROGRESS: {WorkOrder.Status.DONE, WorkOrder.Status.CANCELLED},
}


def transition(order: WorkOrder, new_status: str, user=None) -> WorkOrder:
    if new_status not in _TRANSITIONS.get(order.status, set()):
        raise WorkOrderError(
            f"Переход {order.get_status_display()} → {WorkOrder.Status(new_status).label} недопустим"
        )
    if new_status == WorkOrder.Status.SUBMITTED:
        return submit(order, user)
    order.status = new_status
    if new_status == WorkOrder.Status.APPROVED:
        order.approved_by = user
        if order.assignee_id is None:
            order.assignee = brigade_for(order.node)
    order.save()
    return order


def brigade_for(node):
    """
    Исполнитель по умолчанию — бригадир бригады, в чью зону входит объект (ближайшая по дереву).
    Руководитель может переназначить заявку; без бригады в зоне исполнитель остаётся пустым.
    """
    from apps.accounts.models import Team, TeamKind

    teams = [
        t
        for t in Team.objects.filter(kind=TeamKind.BRIGADE, lead__isnull=False).select_related(
            "scope_node", "lead"
        )
        if t.scope_node and node.path.startswith(t.scope_node.path)
    ]
    if not teams:
        return None
    return max(teams, key=lambda t: t.scope_node.depth).lead


# ---------- система учёта заявок заказчика (help desk) ----------

# Статус help desk → наш статус; заявка двигается только вперёд
_EXTERNAL = {
    "accepted": WorkOrder.Status.SUBMITTED,
    "assigned": WorkOrder.Status.SUBMITTED,
    "in_progress": WorkOrder.Status.IN_PROGRESS,
    "done": WorkOrder.Status.DONE,
    "closed": WorkOrder.Status.DONE,
}
CLOSED_LABEL = "Закрыта"
_ORDER = [
    WorkOrder.Status.DRAFT,
    WorkOrder.Status.APPROVED,
    WorkOrder.Status.SUBMITTED,
    WorkOrder.Status.IN_PROGRESS,
    WorkOrder.Status.DONE,
]


def _client():
    from apps.integrations.clients import HelpdeskClient

    return HelpdeskClient()


def submit(order: WorkOrder, user=None) -> WorkOrder:
    """Передать утверждённую заявку в help desk: там она получает свой номер и живёт своим циклом."""
    import httpx

    payload = {
        "number": order.number,
        "title": order.title,
        "description": order.description,
        "priority": order.priority,
        "work_type": order.work_type,
        "node": order.node.name,
        "due_at": order.due_at.isoformat(),
    }
    try:
        ticket = _client().submit(payload)
    except httpx.HTTPError as exc:
        raise WorkOrderError(f"Система заявок недоступна: {exc}") from exc
    order.status = WorkOrder.Status.SUBMITTED
    _apply_external(order, ticket)
    order.save()
    _incident_event(order, user, f"Заявка {order.number} передана в систему заявок ({order.external_id})")
    return order


def _apply_external(order: WorkOrder, ticket: dict) -> None:
    order.external_id = ticket["id"]
    order.external_status = ticket.get("status_label", ticket.get("status", ""))
    order.external_assignee = ticket.get("assignee") or ""
    order.external_history = ticket.get("history", [])
    order.external_synced_at = timezone.now()
    if ticket.get("report"):
        order.report = ticket["report"]


def _incident_event(order: WorkOrder, user, text: str) -> None:
    if order.incident_id:
        IncidentEvent.objects.create(
            incident_id=order.incident_id,
            kind=IncidentEvent.Kind.WORKORDER,
            actor=user,
            text=text,
            payload={"workorder_id": order.pk},
        )


def sync_external() -> dict:
    """Забрать статусы заявок из help desk (только чтение) и продвинуть наши заявки."""
    import httpx

    from .models import MaintenanceRecommendation

    # Опрашиваем, пока заявка не закрыта в help desk: «выполнена» ещё может закрыться с уточнённым отчётом
    orders = {
        o.external_id: o
        for o in WorkOrder.objects.exclude(external_id="")
        .filter(status__in=(WorkOrder.Status.SUBMITTED, WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.DONE))
        .exclude(external_status=CLOSED_LABEL)
    }
    if not orders:
        return {"checked": 0, "changed": 0}
    try:
        tickets = _client().statuses(list(orders))
    except httpx.HTTPError:
        return {"checked": len(orders), "changed": 0, "error": "help desk недоступен"}
    changed = 0
    for external_id, ticket in tickets.items():
        order = orders.get(external_id)
        if order is None:
            continue
        before = (order.status, order.external_status, order.external_assignee)
        _apply_external(order, ticket)
        target = _EXTERNAL.get(ticket.get("status"))
        if target and _ORDER.index(target) > _ORDER.index(order.status):
            order.status = target
            text = {
                WorkOrder.Status.IN_PROGRESS: f"Заявка {order.number}: бригада приступила ({order.external_assignee})",
                WorkOrder.Status.DONE: f"Заявка {order.number} выполнена: {order.report}",
            }.get(target)
            if text:
                _incident_event(order, None, text)
            if target == WorkOrder.Status.DONE and order.recommendation_id:
                MaintenanceRecommendation.objects.filter(pk=order.recommendation_id).update(
                    status=MaintenanceRecommendation.Status.DONE
                )
        order.save()
        changed += before != (order.status, order.external_status, order.external_assignee)
    return {"checked": len(orders), "changed": changed}
