"""
Рекомендации по техническому обслуживанию (ТЗ §6, §8): из прогнозов, качества данных и реестра
оборудования. Рекомендация — не заявка: её принимает или отклоняет диспетчер/руководитель,
а черновик заявки создаётся из рекомендации одной кнопкой.

Источники:
    прогноз отказа датчика (высокий и критический уровень) → проверка или замена датчика;
    прогноз превышения метана → калибровка сигнализатора и проверка вентиляции;
    прогноз подтопления → обслуживание насосов АНС;
    молчание регулярного канала и низкий Data Health Score → проверка канала и связи;
    просроченное ТО по реестру оборудования → плановое ТО; риск по каналам единицы поднимает приоритет;
    фактическое состояние по осмотру «требует ремонта» / «неисправно» → ремонт или замена.
Открытая рекомендация на тот же объект (канал/единицу) и вид работ обновляется, а не дублируется.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q

from apps.forecasting.models import ChannelHealth, ChannelRisk, ForecastTask, RiskLevel

from .models import MaintenanceRecommendation, WorkType

LEVELS = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
DUE_DAYS = {RiskLevel.CRITICAL: 1, RiskLevel.HIGH: 3, RiskLevel.MEDIUM: 7, RiskLevel.LOW: 14}
OVERDUE_LIMIT = 150  # рекомендаций по просроченному ТО за раз — самые запущенные и рискованные
OPEN = (MaintenanceRecommendation.Status.NEW, MaintenanceRecommendation.Status.ACCEPTED)

EQUIPMENT_WORK = {
    "sensor": WorkType.INSPECTION,
    "pump": WorkType.PUMP_SERVICE,
    "fan": WorkType.VENTILATION,
    "ups": WorkType.POWER_CHECK,
    "cabinet": WorkType.POWER_CHECK,
    "door": WorkType.SECURITY,
    "hatch": WorkType.SECURITY,
}


@dataclass
class Draft:
    node_id: int
    work_type: str
    priority: str
    rationale: str
    channel_id: int | None = None
    equipment_id: int | None = None
    prediction_id: int | None = None


def _from_risks(today: date) -> list[Draft]:
    drafts = []
    risks = ChannelRisk.objects.filter(risk_level__in=[RiskLevel.HIGH, RiskLevel.CRITICAL]).select_related(
        "channel__node", "channel__sensor_type"
    )
    for r in risks:
        factors = "; ".join(f["title"] for f in r.factors[:3]) or "совокупность признаков"
        ch = r.channel
        if r.task == ForecastTask.SENSOR_FAILURE:
            chronic = any(f["feature"] in ("fault_days_90", "faults_90") for f in r.factors)
            work = WorkType.SENSOR_REPLACEMENT if chronic else WorkType.INSPECTION
            text = f"Прогноз отказа канала «{ch.name}» на {r.probability:.0%} в ближайшие сутки. {factors}."
        elif r.task == ForecastTask.GAS:
            work = WorkType.CALIBRATION
            text = (
                f"Прогноз превышения 1 % метана по «{ch.name}» ({r.probability:.0%}). {factors}. "
                "Проверить калибровку сигнализатора и работу вентиляции участка."
            )
        elif r.task == ForecastTask.FLOOD:
            work = WorkType.PUMP_SERVICE
            text = f"Прогноз тревоги затопления по «{ch.name}» ({r.probability:.0%}). {factors}. Проверить насосы АНС и приямок."
        else:
            continue
        drafts.append(Draft(ch.node_id, work, r.risk_level, text, channel_id=ch.pk))
    return drafts


def _from_health() -> list[Draft]:
    drafts = []
    rows = ChannelHealth.objects.filter(Q(silent=True) | Q(score__lt=40)).select_related("channel")
    for h in rows:
        if h.silent:
            text = f"Канал «{h.channel.name}» молчит с {h.silent_since:%d.%m.%Y %H:%M}: проверить связь и питание датчика."
            priority = RiskLevel.MEDIUM
        else:
            weak = [k for k, v in h.components.items() if v is not None and v < 0.5]
            text = f"Низкое качество данных канала «{h.channel.name}» (балл {h.score}): {', '.join(weak) or 'несколько составляющих'}."
            priority = RiskLevel.LOW
        drafts.append(Draft(h.channel.node_id, WorkType.INSPECTION, priority, text, channel_id=h.channel_id))
    return drafts


def _from_registry(today: date) -> list[Draft]:
    from apps.assets.models import Equipment

    risky = dict(
        ChannelRisk.objects.filter(
            risk_level__in=[RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        ).values_list("channel_id", "risk_level")
    )
    candidates = []
    for eq in (
        Equipment.objects.filter(is_active=True)
        .exclude(last_maintenance_at=None)
        .exclude(maintenance_interval_days=None)
        .select_related("node")
        .prefetch_related("channels")
    ):
        due = eq.last_maintenance_at + timedelta(days=eq.maintenance_interval_days)
        if due >= today:
            continue
        overdue = (today - due).days
        channel_risk = max((LEVELS.index(risky[c.pk]) for c in eq.channels.all() if c.pk in risky), default=0)
        score = overdue / eq.maintenance_interval_days * eq.node.criticality + channel_risk
        candidates.append((score, eq, overdue, channel_risk))
    candidates.sort(key=lambda t: -t[0])
    drafts = []
    for _, eq, overdue, channel_risk in candidates[:OVERDUE_LIMIT]:
        priority = LEVELS[
            max(1, min(3, channel_risk + (1 if overdue > eq.maintenance_interval_days / 2 else 0)))
        ]
        text = (
            f"Плановое ТО «{eq.name}» просрочено на {overdue} сут (регламент — раз в {eq.maintenance_interval_days} сут)."
            + (" По каналам единицы есть повышенный риск отказа." if channel_risk else "")
        )
        work = EQUIPMENT_WORK.get(eq.kind, WorkType.INSPECTION)
        if eq.kind == "sensor" and "метан" in eq.name.lower():
            work = WorkType.CALIBRATION
        drafts.append(Draft(eq.node_id, work, priority, text, equipment_id=eq.pk))
    return drafts


def _from_condition() -> list[Draft]:
    """Оборудование, которое по последнему осмотру требует ремонта или неисправно."""
    from apps.assets.models import Equipment, EquipmentCondition

    priority = {
        EquipmentCondition.NEEDS_REPAIR: RiskLevel.HIGH,
        EquipmentCondition.FAULTY: RiskLevel.CRITICAL,
    }
    drafts = []
    for eq in Equipment.objects.filter(is_active=True, condition__in=list(priority)).select_related("node"):
        work = (
            WorkType.SENSOR_REPLACEMENT
            if eq.kind == "sensor"
            else EQUIPMENT_WORK.get(eq.kind, WorkType.INSPECTION)
        )
        when = f" ({eq.condition_at:%d.%m.%Y})" if eq.condition_at else ""
        text = f"По последнему осмотру{when} «{eq.name}»: {eq.get_condition_display().lower()}."
        drafts.append(Draft(eq.node_id, work, priority[eq.condition], text, equipment_id=eq.pk))
    return drafts


@transaction.atomic
def generate(today: date | None = None) -> dict:
    from django.utils import timezone

    today = today or timezone.localdate()
    drafts = _from_risks(today) + _from_health() + _from_registry(today) + _from_condition()
    created = updated = 0
    for d in drafts:
        key = Q(node_id=d.node_id, work_type=d.work_type, status__in=OPEN)
        key &= Q(channel_id=d.channel_id) if d.channel_id else Q(equipment_id=d.equipment_id)
        due = today + timedelta(days=DUE_DAYS[d.priority])
        current = MaintenanceRecommendation.objects.filter(key).first()
        if current:
            if LEVELS.index(d.priority) > LEVELS.index(current.priority):
                current.priority, current.due_date = d.priority, min(current.due_date, due)
            current.rationale = d.rationale
            current.save(update_fields=["priority", "due_date", "rationale", "updated_at"])
            updated += 1
            continue
        MaintenanceRecommendation.objects.create(
            node_id=d.node_id,
            channel_id=d.channel_id,
            equipment_id=d.equipment_id,
            work_type=d.work_type,
            priority=d.priority,
            due_date=due,
            rationale=d.rationale,
        )
        created += 1
    return {"drafts": len(drafts), "created": created, "updated": updated}
