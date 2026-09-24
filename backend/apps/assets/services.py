import csv
from collections import defaultdict
from pathlib import Path

from django.db import transaction

from apps.normalization.domain.defaults import DEFAULT_PROFILES
from apps.normalization.models import SensorProfile
from apps.topology.models import Node
from apps.topology.services import unlinked_node

from .domain.naming import parse_name
from .models import Channel, IncidentDomain, SensorType

# Направление риска по типу датчика. Насосы и затопление — подтопление; тепловые,
# дымовые и ручные извещатели — пожар; питание и ИБП — электропитание.
SENSOR_DOMAIN = {
    "Газовый датчик": IncidentDomain.GAS,
    "Датчик дыма": IncidentDomain.FIRE,
    "Тепловой датчик": IncidentDomain.FIRE,
    "Ручной извещатель": IncidentDomain.FIRE,
    "Состояние УИР-Р": IncidentDomain.FIRE,
    "Датчик температуры": IncidentDomain.CLIMATE,
    "Датчик затопления": IncidentDomain.FLOOD,
    "Состояние насоса": IncidentDomain.FLOOD,
    "Состояние фазы": IncidentDomain.POWER,
    "ИБП": IncidentDomain.POWER,
    "Состояние вентилятора": IncidentDomain.PROCESS,
    "Переключатель": IncidentDomain.PROCESS,
}
SYSTEM_DOMAIN = {
    "Охранная подсистема": IncidentDomain.INTRUSION,
    "Газовая охрана": IncidentDomain.GAS,
    "Пожарная охрана": IncidentDomain.FIRE,
    "Температурная подсистема": IncidentDomain.CLIMATE,
    "Диагностическая подсистема": IncidentDomain.POWER,
}
PROFILE_BY_TYPE = {t: code for code, spec in DEFAULT_PROFILES.items() for t in spec["sensor_types"]}


def _sensor_type(name: str, system: str, cache: dict, profiles: dict) -> SensorType:
    if name in cache:
        return cache[name]
    domain = SENSOR_DOMAIN.get(name) or SYSTEM_DOMAIN.get(system, IncidentDomain.PROCESS)
    sensor_type, _ = SensorType.objects.get_or_create(
        name=name,
        defaults={
            "system_type": system,
            "domain": domain,
            "profile": profiles.get(PROFILE_BY_TYPE.get(name, "discrete")),
        },
    )
    cache[name] = sensor_type
    return sensor_type


@transaction.atomic
def import_channels(path: str | Path) -> dict:
    """
    Справочник каналов → Channel. Идемпотентно по ид_канала_данных: существующие каналы
    обновляются (объект, тип, название, пикет), правки профиля в админке сохраняются.
    """
    profiles = {p.code: p for p in SensorProfile.objects.all()}
    nodes = {n.external_id: n for n in Node.objects.exclude(external_id=None)}
    existing = {c.external_id: c for c in Channel.objects.all()}
    types: dict[str, SensorType] = {}
    fallback = None
    to_create, to_update = [], []
    unlinked = 0

    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            ext_id = int(row["ид_канала_данных"])
            node = nodes.get(int(row["ид_объект"])) if row.get("ид_объект") else None
            if node is None:
                fallback = fallback or unlinked_node()
                node, unlinked = fallback, unlinked + 1
            parsed = parse_name(row["название_датчика"])
            fields = {
                "node": node,
                "sensor_type": _sensor_type(
                    row["тип_датчика"].strip(), row["тип_инж_системы"].strip(), types, profiles
                ),
                "tag": row["тег_инженерной_системы"].strip(),
                "name": row["название_датчика"].strip(),
                "picket": parsed.picket,
                "location_hint": parsed.location_hint[:64],
                "in_catalog": True,
            }
            if channel := existing.get(ext_id):
                for key, value in fields.items():
                    setattr(channel, key, value)
                to_update.append(channel)
            else:
                to_create.append(Channel(external_id=ext_id, **fields))

    Channel.objects.bulk_create(to_create, batch_size=2000)
    Channel.objects.bulk_update(
        to_update,
        ["node", "sensor_type", "tag", "name", "picket", "location_hint", "in_catalog"],
        batch_size=2000,
    )
    _update_node_pickets()
    return {
        "created": len(to_create),
        "updated": len(to_update),
        "unlinked": unlinked,
        "sensor_types": len(types),
        "with_picket": Channel.objects.exclude(picket=None).count(),
    }


def _update_node_pickets() -> None:
    """Диапазон пикетов объекта = min/max пикетов его каналов — основа линейной схемы."""
    ranges: dict[int, list] = defaultdict(list)
    for node_id, picket in Channel.objects.exclude(picket=None).values_list("node_id", "picket"):
        ranges[node_id].append(picket)
    nodes = list(Node.objects.filter(pk__in=ranges))
    for node in nodes:
        node.picket_from, node.picket_to = min(ranges[node.pk]), max(ranges[node.pk])
    Node.objects.bulk_update(nodes, ["picket_from", "picket_to"])


def ensure_channels(external_ids: set[int]) -> int:
    """
    Каналы, встреченные в журнале, но отсутствующие в справочнике: заводятся с in_catalog=False
    под служебным узлом, чтобы история не терялась, а качество справочника было видно в отчёте.
    """
    missing = external_ids - set(
        Channel.objects.filter(external_id__in=external_ids).values_list("external_id", flat=True)
    )
    if not missing:
        return 0
    node = unlinked_node()
    Channel.objects.bulk_create(
        [
            Channel(external_id=i, node=node, name=f"Канал {i} (нет в справочнике)", in_catalog=False)
            for i in missing
        ],
        batch_size=2000,
        ignore_conflicts=True,
    )
    return len(missing)
