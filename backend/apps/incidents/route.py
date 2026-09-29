"""
Маршрут движения нарушителя по сработкам охранной системы.

У заказчика сработки охраны — разновидность аварии («террор, проникновение нарушителя»), и по ним
рисуется маршрут: люк → дверь → движение в отсеке → следующий отсек. Сигналы карточки НСД идут
по времени; подряд идущие сработки одного датчика склеиваются в один шаг (датчик движения пишет
десятки раз, пока человек рядом). Точка шага — место датчика на карте: своя точка из редактора
(в том числе на плане этажа) или место на контуре по пикету, как на карте мониторинга.

Направление — по пикетам последних двух шагов: коллектор линейный, и «пикет растёт» понятнее
диспетчеру, чем азимут.
"""

from __future__ import annotations

import math
from itertools import pairwise

from apps.assets import placement
from apps.assets.models import Channel
from apps.topology import geo
from apps.topology.floors import floor_dict, floors_of
from apps.topology.models import Node, NodeKind

from .models import Incident, IncidentType

MAX_ALERTS = 2000


def object_of(node: Node) -> Node:
    """Объект (комплекс) узла: у частей объекта (шкаф, ДП) контура обычно нет, он у комплекса."""
    if node.kind == NodeKind.COMPLEX:
        return node
    paths = [node.path[:i] for i in range(Node.steplen, len(node.path), Node.steplen)]
    return Node.objects.filter(path__in=paths, kind=NodeKind.COMPLEX).order_by("-depth").first() or node


def _meters(a: list[float], b: list[float]) -> float:
    lat = math.radians((a[1] + b[1]) / 2)
    dx = math.radians(b[0] - a[0]) * 6_371_000 * math.cos(lat)
    dy = math.radians(b[1] - a[1]) * 6_371_000
    return math.hypot(dx, dy)


def _heading(steps: list[dict]) -> str:
    known = [s for s in steps if s["picket"] is not None]
    if len(known) < 2 or known[-1]["picket"] == known[-2]["picket"]:
        return ""
    last, prev = known[-1]["picket"], known[-2]["picket"]
    return f"в сторону {'увеличения' if last > prev else 'уменьшения'} пикетов (ПК{prev:g} → ПК{last:g})"


def intrusion_route(incident: Incident) -> dict | None:
    if incident.type != IncidentType.INTRUSION:
        return None
    obj = object_of(incident.node)
    alerts = list(
        incident.alerts.filter(channel__isnull=False)
        .select_related("channel__floor")
        .order_by("raised_at", "pk")[:MAX_ALERTS]
    )
    if not alerts:
        return None
    channels = Channel.objects.filter(node__path__startswith=obj.path, is_active=True).select_related(
        "sensor_type"
    )
    where = placement.positions(obj.geometry, channels)
    steps: list[dict] = []
    for alert in alerts:
        c = alert.channel
        if steps and steps[-1]["channel"] == c.pk:
            steps[-1]["until"] = alert.raised_at
            steps[-1]["count"] += 1
            continue
        position, placed = where.get(c.pk, (c.location, bool(c.location)))
        steps.append(
            {
                "n": len(steps) + 1,
                "channel": c.pk,
                "name": c.name,
                "at": alert.raised_at,
                "until": alert.raised_at,
                "count": 1,
                "position": position,
                "placed": placed,
                "picket": float(c.picket) if c.picket is not None else None,
                "floor": c.floor_id,
                "floor_title": c.floor.title if c.floor_id else None,
            }
        )
    points = [s["position"] for s in steps if s["position"]]
    distance = sum(_meters(a, b) for a, b in pairwise(points))
    last = steps[-1]
    return {
        "object": obj.pk,
        "object_name": obj.name,
        "geometry": obj.geometry,
        "line": {"type": "LineString", "coordinates": points} if len(points) >= 2 else None,
        "steps": steps,
        "distance_m": round(distance),
        "duration_s": int((last["until"] - steps[0]["at"]).total_seconds()),
        "last": {"name": last["name"], "at": last["until"], "floor_title": last["floor_title"]},
        "heading": _heading(steps),
        "floors": [floor_dict(f) for f in floors_of(obj)],
        "map": geo.map_config(),
    }
