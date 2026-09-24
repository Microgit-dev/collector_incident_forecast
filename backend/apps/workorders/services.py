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
    order.status = new_status
    if new_status == WorkOrder.Status.APPROVED:
        order.approved_by = user
    order.save()
    return order
