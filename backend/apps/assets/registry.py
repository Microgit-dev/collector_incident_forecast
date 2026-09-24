"""
Эмуляция реестра оборудования по справочнику каналов (у заказчика реестра нет).

Детерминирована: случайные даты берутся из генератора с зерном = ид канала, поэтому повторный
запуск даёт тот же реестр. Дата ввода — первое появление канала в журналах; для каналов, которые
были в журналах с самого начала истории, — случайная дата раньше. Пересоздаются только записи
с source=emulated: отредактированные вручную записи нужно переводить в source=manual.
"""

import random
from collections import defaultdict
from datetime import date, timedelta

from django.db import connection, transaction
from django.utils import timezone

from .domain.reliability import BY_SENSOR_TYPE, CABINET, CABINET_TYPES, Norm
from .models import Channel, Equipment

HISTORY_EDGE_DAYS = 45  # канал виден с первых недель истории → установлен раньше её начала
EARLIEST_INSTALL = date(2010, 1, 1)


def _first_seen() -> dict[int, date]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT channel_id, min(day) FROM telemetry_channeldaily GROUP BY channel_id")
        return dict(cursor.fetchall())


def _dates(seed: int, first_seen: date | None, history_start: date | None, norm: Norm, today: date):
    rng = random.Random(seed)
    if first_seen and history_start and (first_seen - history_start).days > HISTORY_EDGE_DAYS:
        commissioned = first_seen
    else:
        latest = history_start or today
        commissioned = EARLIEST_INSTALL + timedelta(days=rng.randint(0, (latest - EARLIEST_INSTALL).days))
    # около 20 % единиц — с просроченным ТО: так выглядит реальный парк и есть что приоритизировать
    since = rng.randint(0, int(norm.maintenance_days * 1.25))
    last_maintenance = max(commissioned, today - timedelta(days=since))
    return commissioned, last_maintenance


@transaction.atomic
def emulate_registry() -> dict[str, int]:
    today = timezone.localdate()
    first_seen = _first_seen()
    history_start = min(first_seen.values()) if first_seen else None
    channels = list(
        Channel.objects.filter(in_catalog=True, sensor_type__isnull=False).select_related(
            "sensor_type", "node"
        )
    )
    Equipment.objects.filter(source="emulated").delete()

    units: list[tuple[Equipment, list[int]]] = []
    cabinets: dict[int, list[Channel]] = defaultdict(list)
    for ch in channels:
        type_name = ch.sensor_type.name
        if type_name in CABINET_TYPES:
            cabinets[ch.node_id].append(ch)
            continue
        norm = BY_SENSOR_TYPE.get(type_name)
        if norm is None:
            continue
        commissioned, maintained = _dates(ch.external_id, first_seen.get(ch.pk), history_start, norm, today)
        units.append(
            (
                Equipment(
                    kind=norm.kind,
                    node_id=ch.node_id,
                    name=f"{norm.label}: {ch.name}"[:255],
                    inventory_number=f"EMU-{ch.external_id}",
                    picket=ch.picket,
                    commissioned_at=commissioned,
                    last_maintenance_at=maintained,
                    maintenance_interval_days=norm.maintenance_days,
                    mtbf_hours=norm.mtbf_hours,
                ),
                [ch.pk],
            )
        )
    for node_id, members in cabinets.items():
        node = members[0].node
        seen = [first_seen[c.pk] for c in members if c.pk in first_seen]
        commissioned, maintained = _dates(
            node.external_id or node.pk, min(seen) if seen else None, history_start, CABINET, today
        )
        pickets = [c.picket for c in members if c.picket is not None]
        units.append(
            (
                Equipment(
                    kind=CABINET.kind,
                    node_id=node_id,
                    name=f"{CABINET.label}: {node.name}"[:255],
                    inventory_number=f"EMU-CAB-{node.external_id or node.pk}",
                    picket=min(pickets) if pickets else None,
                    commissioned_at=commissioned,
                    last_maintenance_at=maintained,
                    maintenance_interval_days=CABINET.maintenance_days,
                    mtbf_hours=CABINET.mtbf_hours,
                ),
                [c.pk for c in members],
            )
        )

    created = Equipment.objects.bulk_create([u for u, _ in units], batch_size=2000)
    through = Equipment.channels.through
    through.objects.bulk_create(
        [
            through(equipment_id=eq.pk, channel_id=ch_id)
            for eq, (_, ids) in zip(created, units, strict=True)
            for ch_id in ids
        ],
        batch_size=5000,
    )
    overdue = sum(
        1 for eq in created if eq.last_maintenance_at + timedelta(days=eq.maintenance_interval_days) < today
    )
    return {"equipment": len(created), "cabinets": len(cabinets), "maintenance_overdue": overdue}
