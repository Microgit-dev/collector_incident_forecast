"""
Схема коллекторов по пикетам (ТЗ §10). Координат у заказчика нет, поэтому схема линейная:
x — пикет вдоль трассы, y — номер строки объекта. Отдаётся GeoJSON FeatureCollection:
- route — трасса объекта (комплекса) от минимального до максимального пикета его каналов;
- object — охраняемые объекты и шкафы внутри комплекса (полоса под трассой);
- segment — участок трассы шириной `bin` пикетов: каналы, состояния, Data Health, риск по задачам;
- incident — открытая карточка, привязанная к медианному пикету её каналов;
- workorder — открытая заявка (отдельный слой, см. workorders_layer).

Слои зависят от прав: карточки видит тот, кто видит инциденты, риск и Data Health — тот, кто видит
прогнозы. Бригада получает трассу, состояния каналов и свои заявки.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from statistics import median

from apps.assets.models import Channel
from apps.forecasting.models import ChannelHealth, ChannelRisk
from apps.incidents.models import Alert, Incident
from apps.telemetry.models import ChannelState
from apps.topology.models import Node
from apps.topology.selectors import scope_queryset

LEVELS = ("low", "medium", "high", "critical")
ABNORMAL = ("alarm", "fault", "power_loss", "unknown")
OPEN = (Incident.Status.NEW, Incident.Status.ACKNOWLEDGED, Incident.Status.IN_PROGRESS)
NICE_BINS = (1, 2, 5, 10, 20, 25, 50, 100)
TARGET_SEGMENTS = 60


def _nice_bin(span: float) -> int:
    raw = max(span, 1) / TARGET_SEGMENTS
    return next((b for b in NICE_BINS if b >= raw), NICE_BINS[-1])


def to_wkt(geometry: dict) -> str:
    """GeoJSON-геометрия схемы → WKT (ТЗ §7: геоданные GeoJSON и WKT)."""
    coords = geometry["coordinates"]
    if geometry["type"] == "Point":
        return f"POINT ({coords[0]:g} {coords[1]:g})"
    return "LINESTRING (" + ", ".join(f"{x:g} {y:g}" for x, y in coords) + ")"


def _line(a: float, b: float, y: float) -> dict:
    return {"type": "LineString", "coordinates": [[a, y], [b, y]]}


def scheme(
    user, *, complex_id: int | None = None, task: str | None = None, bin_size: int | None = None
) -> dict:
    step = Node.steplen
    channels = scope_queryset(
        Channel.objects.filter(is_active=True, picket__isnull=False, node__depth__gte=2), user, "node"
    ).select_related("node", "sensor_type")
    if complex_id:
        root = Node.objects.get(pk=complex_id)
        channels = channels.filter(node__path__startswith=root.path)
    by_complex: dict[str, list[Channel]] = defaultdict(list)
    for ch in channels:
        by_complex[ch.node.path[: 2 * step]].append(ch)
    ids = [c.pk for chs in by_complex.values() for c in chs]
    # Строка схемы — комплекс, даже если зона ответственности пользователя уже (один объект внутри него)
    complexes = {n.path: n for n in Node.objects.filter(path__in=list(by_complex)).order_by("name")}

    states = dict(
        ChannelState.objects.filter(channel_id__in=ids, facet="primary").values_list("channel_id", "state")
    )
    health = {
        cid: (score, silent)
        for cid, score, silent in ChannelHealth.objects.filter(channel_id__in=ids).values_list(
            "channel_id", "score", "silent"
        )
    }
    if not user.has_perm("forecasting.view_channelhealth"):
        health = {}
    risk_rows = ChannelRisk.objects.filter(channel_id__in=ids)
    if not user.has_perm("forecasting.view_channelrisk"):
        risk_rows = risk_rows.none()
    if task:
        risk_rows = risk_rows.filter(task=task)
    risks: dict[int, list[tuple]] = defaultdict(list)
    for cid, t, prob, level in risk_rows.values_list("channel_id", "task", "probability", "risk_level"):
        risks[cid].append((t, prob, level))

    features: list[dict] = []
    rows = [path for path in complexes if path in by_complex]
    for y, path in enumerate(rows):
        node = complexes[path]
        chs = by_complex[path]
        pickets = [float(c.picket) for c in chs]
        lo, hi = math.floor(min(pickets)), math.ceil(max(pickets))
        size = bin_size or _nice_bin(hi - lo)
        segments: dict[int, list[Channel]] = defaultdict(list)
        for c in chs:
            segments[int((float(c.picket) - lo) // size)].append(c)

        route_level = "low"
        for idx, members in sorted(segments.items()):
            props = _segment(members, states, health, risks)
            if LEVELS.index(props["risk_level"]) > LEVELS.index(route_level):
                route_level = props["risk_level"]
            a = lo + idx * size
            features.append(
                {
                    "type": "Feature",
                    "geometry": _line(a, a + size, y),
                    "properties": {"kind": "segment", "complex": node.pk, "from": a, "to": a + size, **props},
                }
            )

        subs = defaultdict(list)
        for c in chs:
            if c.node.depth > 2:
                subs[c.node].append(float(c.picket))
        for sub, values in sorted(subs.items(), key=lambda kv: min(kv[1])):
            a = float(sub.picket_from) if sub.picket_from is not None else min(values)
            b = float(sub.picket_to) if sub.picket_to is not None else max(values)
            features.append(
                {
                    "type": "Feature",
                    "geometry": _line(a, max(b, a + size / 2), y),
                    "properties": {
                        "kind": "object",
                        "complex": node.pk,
                        "node": sub.pk,
                        "name": sub.name,
                        "node_kind": sub.kind,
                        "channels": len(values),
                    },
                }
            )

        features.append(
            {
                "type": "Feature",
                "geometry": _line(lo, hi, y),
                "properties": {
                    "kind": "route",
                    "complex": node.pk,
                    "name": node.name,
                    "row": y,
                    "picket_from": lo,
                    "picket_to": hi,
                    "bin": size,
                    "channels": len(chs),
                    "risk_level": route_level,
                    "criticality": node.criticality,
                },
            }
        )
    if user.has_perm("incidents.view_incident"):
        features.extend(_incidents(user, complexes, rows, step))
    return {
        "type": "FeatureCollection",
        "properties": {"rows": len(rows), "task": task, "crs": "схема: x — пикет, y — строка объекта"},
        "features": features,
    }


def _segment(members: list[Channel], states: dict, health: dict, risks: dict) -> dict:
    state_counts = Counter(states[c.pk] for c in members if c.pk in states)
    scores = [health[c.pk][0] for c in members if c.pk in health]
    silent = sum(1 for c in members if c.pk in health and health[c.pk][1])
    by_task: dict[str, float] = {}
    ranked = []
    level = "low"
    for c in members:
        for t, prob, lvl in risks.get(c.pk, ()):
            by_task[t] = max(by_task.get(t, 0), prob)
            if LEVELS.index(lvl) > LEVELS.index(level):
                level = lvl
            ranked.append((LEVELS.index(lvl), prob, c, t, lvl))
    ranked.sort(key=lambda r: (-r[0], -r[1]))
    return {
        "channels": len(members),
        "states": {s: state_counts[s] for s in ABNORMAL if state_counts[s]},
        "silent": silent,
        "health_min": min(scores) if scores else None,
        "health_avg": round(sum(scores) / len(scores)) if scores else None,
        "risk_level": level,
        "risk_by_task": {t: round(p, 3) for t, p in by_task.items()},
        "top": [
            {
                "channel": c.pk,
                "name": c.name,
                "picket": float(c.picket),
                "task": t,
                "probability": round(p, 3),
                "risk_level": lvl,
                "state": states.get(c.pk),
            }
            for _, p, c, t, lvl in ranked[:5]
            if lvl != "low"
        ],
    }


def _incidents(user, complexes: dict, rows: list[str], step: int) -> list[dict]:
    row_of = {path: y for y, path in enumerate(rows)}
    incidents = scope_queryset(Incident.objects.filter(status__in=OPEN), user, "node").select_related("node")
    pickets: dict[int, list[float]] = defaultdict(list)
    for incident_id, picket in Alert.objects.filter(
        incident__in=incidents, channel__picket__isnull=False
    ).values_list("incident_id", "channel__picket")[:20000]:
        pickets[incident_id].append(float(picket))
    out = []
    for i in incidents:
        y = row_of.get(i.node.path[: 2 * step])
        values = pickets.get(i.pk)
        if y is None or not values:
            continue
        out.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [median(values), y]},
                "properties": {
                    "kind": "incident",
                    "id": i.pk,
                    "title": i.title,
                    "type": i.type,
                    "severity": i.severity,
                    "status": i.status,
                    "is_forecast": i.is_forecast,
                    "priority": round(i.priority),
                    "picket_from": min(values),
                    "picket_to": max(values),
                },
            }
        )
    return out


def workorders_layer(user, result: dict) -> list[dict]:
    """
    Открытые заявки на трассе: пикет оборудования, иначе медиана пикетов каналов карточки, иначе
    медиана каналов объекта. Считается на каждый запрос (не кешируется): бригада видит только свои.
    """
    from django.utils import timezone

    from apps.workorders.models import WorkOrder

    if not user.has_perm("workorders.view_workorder"):
        return []
    rows = {
        f["properties"]["complex"]: f["properties"]["row"]
        for f in result["features"]
        if f["properties"]["kind"] == "route"
    }
    if not rows:
        return []
    step = Node.steplen
    complex_of = dict(Node.objects.filter(pk__in=rows).values_list("path", "pk"))
    orders = scope_queryset(
        WorkOrder.objects.exclude(status__in=[WorkOrder.Status.DONE, WorkOrder.Status.CANCELLED]),
        user,
        "node",
    ).select_related("node", "equipment", "assignee")
    if user.has_perm("workorders.execute_workorder") and not user.has_perm("workorders.add_workorder"):
        orders = orders.filter(assignee=user)
    orders = [o for o in orders if complex_of.get(o.node.path[: 2 * step]) in rows]

    by_incident: dict[int, list[float]] = defaultdict(list)
    for incident_id, picket in Alert.objects.filter(
        incident_id__in=[o.incident_id for o in orders if o.incident_id], channel__picket__isnull=False
    ).values_list("incident_id", "channel__picket"):
        by_incident[incident_id].append(float(picket))
    by_node: dict[int, list[float]] = defaultdict(list)
    for node_id, picket in Channel.objects.filter(
        node_id__in={o.node_id for o in orders}, picket__isnull=False
    ).values_list("node_id", "picket"):
        by_node[node_id].append(float(picket))

    now = timezone.now()
    out = []
    for order in orders:
        if order.equipment and order.equipment.picket is not None:
            picket = float(order.equipment.picket)
        elif by_incident.get(order.incident_id):
            picket = median(by_incident[order.incident_id])
        elif order.node.picket_from is not None:
            picket = float(order.node.picket_from)
        elif by_node.get(order.node_id):
            picket = median(by_node[order.node_id])
        else:
            continue
        out.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [picket, rows[complex_of[order.node.path[: 2 * step]]]],
                },
                "properties": {
                    "kind": "workorder",
                    "id": order.pk,
                    "number": order.number,
                    "title": order.title,
                    "status": order.status,
                    "priority": order.priority,
                    "work_type": order.work_type,
                    "due_at": order.due_at.isoformat(),
                    "overdue": order.due_at < now,
                    "node": order.node.name,
                    "assignee": order.assignee.get_full_name() if order.assignee else None,
                    "mine": order.assignee_id == user.pk,
                },
            }
        )
    return out
