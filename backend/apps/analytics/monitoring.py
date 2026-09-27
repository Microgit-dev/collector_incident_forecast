"""
Карта мониторинга — главный экран каждой роли. Зоны и объекты на местности, акцент на зоне
ответственности пользователя; объекты вне зоны — второстепенные: контур и название, у смежных зон —
признак «есть открытые карточки», подробности закрыты (список вне зоны отдаётся постранично).

Что на карте, зависит от прав: карточки — тем, кто видит инциденты; риск и Data Health — тем, кто
видит прогнозы; заявки — всем, кто видит заявки (бригаде — только свои). Раскраска объекта выбирается
в интерфейсе из доступных режимов, режим по умолчанию — по роли.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from django.core.paginator import Paginator
from django.utils import timezone

from apps.assets.models import Channel
from apps.forecasting.models import ChannelHealth, ChannelRisk
from apps.incidents.models import Incident
from apps.telemetry.models import ChannelState
from apps.topology import geo
from apps.topology.models import Node, NodeKind
from apps.topology.selectors import ObjectIndex, has_global_scope, in_scope, scope_paths, zone_of
from apps.workorders.models import WorkOrder

from .workspace import roles_of

LEVELS = ("low", "medium", "high", "critical")
ABNORMAL = ("alarm", "fault", "power_loss", "unknown")
OPEN = (Incident.Status.NEW, Incident.Status.ACKNOWLEDGED, Incident.Status.IN_PROGRESS)
ORDERS_OPEN = (
    WorkOrder.Status.DRAFT,
    WorkOrder.Status.APPROVED,
    WorkOrder.Status.SUBMITTED,
    WorkOrder.Status.IN_PROGRESS,
)
DEFAULT_MODE = {
    "unit_dispatcher": "situation",
    "ods_dispatcher": "situation",
    "head": "situation",
    "analyst": "health",
    "technician": "orders",
    "maintenance_engineer": "orders",
    "observer": "situation",
    "admin": "situation",
}
PAGE = 10


def _max_level(a: str | None, b: str | None) -> str | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if LEVELS.index(a) >= LEVELS.index(b) else b


def modes_for(user) -> list[str]:
    modes = []
    if user.has_perm("incidents.view_incident"):
        modes.append("situation")
    if user.has_perm("forecasting.view_channelrisk"):
        modes.append("risk")
    modes.append("state")
    if user.has_perm("forecasting.view_channelhealth"):
        modes.append("health")
    if user.has_perm("workorders.view_workorder"):
        modes.append("orders")
    return modes


def _is_technician(user) -> bool:
    return user.has_perm("workorders.execute_workorder") and not user.has_perm("workorders.add_workorder")


def _orders_qs(user):
    qs = WorkOrder.objects.filter(status__in=ORDERS_OPEN)
    if _is_technician(user):
        # бригаде — только свои назначенные, черновики её не касаются
        return qs.filter(assignee=user).exclude(status=WorkOrder.Status.DRAFT)
    return qs


def _scope_check(user):
    """Проверка «в зоне ли узел» с одним запросом на пользователя (командирования читаются один раз)."""
    if has_global_scope(user):
        return lambda node: True
    paths = scope_paths(user)
    return lambda node: any(node.path.startswith(p) for p in paths)


def _home_zone(user) -> Node | None:
    return zone_of(user.scope_node) if user.scope_node_id else None


def monitoring_map(user) -> dict:
    """Зоны, объекты (свои — с цифрами, чужие — контуром), маркеры карточек и заявок, сводка."""
    roles = roles_of(user)
    modes = modes_for(user)
    index = ObjectIndex(Node.objects.filter(kind=NodeKind.COMPLEX, is_active=True))
    objects = list(index)
    own_node = _scope_check(user)
    mine = {o.pk for o in objects if own_node(o)}
    home = _home_zone(user)
    adjacent_ids = set(home.adjacent.values_list("pk", flat=True)) if home else set()
    paths = [] if has_global_scope(user) else scope_paths(user)
    seconded = {
        z.pk for z in Node.objects.filter(kind=NodeKind.ZONE) if any(z.path.startswith(p) for p in paths)
    }

    zones = []
    zone_by_path = {}
    for z in Node.objects.filter(kind=NodeKind.ZONE, is_active=True).order_by("name"):
        zone_by_path[z.path] = z
        own = own_node(z) or (user.scope_node_id is not None and user.scope_node.path.startswith(z.path))
        zones.append(
            {
                "id": z.pk,
                "name": z.name,
                "color": z.color or "#1c7ed6",
                "geometry": z.geometry,
                "mine": own,
                "home": home is not None and z.pk == home.pk,
                "adjacent": z.pk in adjacent_ids,
                "seconded": z.pk in seconded and (home is None or z.pk != home.pk),
            }
        )

    def zone_for(obj: Node) -> Node | None:
        best = None
        for length in range(Node.steplen, len(obj.path), Node.steplen):
            best = zone_by_path.get(obj.path[:length], best)
        return best

    # ---- цифры по своим объектам ----
    stats: dict[int, dict] = defaultdict(
        lambda: {
            "channels": 0,
            "abnormal": 0,
            "silent": 0,
            "health_low": 0,
            "risk_level": None,
            "incidents": 0,
            "incident_level": None,
            "escalated": 0,
            "new": 0,
            "orders": 0,
            "approvals": 0,
            "overdue": 0,
        }
    )
    mine_paths = [o.path for o in objects if o.pk in mine]
    obj_of_channel: dict[int, int] = {}
    if mine_paths:
        for cid, path in Channel.objects.filter(is_active=True, node__kind__in=_kinds_under()).values_list(
            "pk", "node__path"
        ):
            obj = index.of_path(path)
            if obj is not None and obj.pk in mine:
                obj_of_channel[cid] = obj.pk
                stats[obj.pk]["channels"] += 1
        for cid in ChannelState.objects.filter(facet="primary", state__in=ABNORMAL).values_list(
            "channel_id", flat=True
        ):
            if cid in obj_of_channel:
                stats[obj_of_channel[cid]]["abnormal"] += 1
        if "health" in modes:
            for cid, score, silent in ChannelHealth.objects.values_list("channel_id", "score", "silent"):
                if cid in obj_of_channel:
                    s = stats[obj_of_channel[cid]]
                    s["silent"] += bool(silent)
                    s["health_low"] += bool(score is not None and score < 40)
        if "risk" in modes:
            for cid, level in ChannelRisk.objects.exclude(risk_level="low").values_list(
                "channel_id", "risk_level"
            ):
                if cid in obj_of_channel:
                    s = stats[obj_of_channel[cid]]
                    s["risk_level"] = _max_level(s["risk_level"], level)

    incident_markers = []
    busy_adjacent: set[int] = set()
    incidents = (
        Incident.objects.filter(status__in=OPEN)
        .select_related("node")
        .only("pk", "severity", "status", "escalation_level", "node__path", "type", "title")
    )
    per_object: dict[int, list[Incident]] = defaultdict(list)
    for i in incidents:
        obj = index.of_path(i.node.path)
        if obj is None:
            continue
        if obj.pk in mine:
            per_object[obj.pk].append(i)
        else:
            z = zone_for(obj)
            if z is not None and z.pk in adjacent_ids:
                busy_adjacent.add(obj.pk)
    if "situation" in modes:
        for pk, items in per_object.items():
            s = stats[pk]
            s["incidents"] = len(items)
            s["escalated"] = sum(1 for i in items if i.escalation_level > 0)
            s["new"] = sum(1 for i in items if i.status == Incident.Status.NEW)
            for i in items:
                s["incident_level"] = _max_level(s["incident_level"], i.severity)
            incident_markers.append({"object": pk, "count": len(items), "level": s["incident_level"]})

    order_markers = []
    if "orders" in modes:
        now = timezone.now()
        per_order: dict[int, list[WorkOrder]] = defaultdict(list)
        for o in _orders_qs(user).select_related("node").only("pk", "status", "due_at", "node__path"):
            obj = index.of_path(o.node.path)
            if obj is not None and obj.pk in mine:
                per_order[obj.pk].append(o)
        for pk, items in per_order.items():
            s = stats[pk]
            s["orders"] = len(items)
            s["approvals"] = sum(1 for o in items if o.status == WorkOrder.Status.DRAFT)
            s["overdue"] = sum(1 for o in items if o.due_at and o.due_at < now)
            order_markers.append(
                {"object": pk, "count": len(items), "approvals": s["approvals"], "overdue": s["overdue"]}
            )

    items = []
    for o in objects:
        z = zone_for(o)
        own = o.pk in mine
        center = geo.centroid(o.geometry)
        item = {
            "id": o.pk,
            "name": o.name,
            "zone": z.pk if z else None,
            "zone_name": z.name if z else None,
            "mine": own,
            "geometry": o.geometry,
            "center": center,
            "placed": o.geometry is not None,
        }
        if own:
            item.update(stats[o.pk], criticality=o.criticality)
        else:
            item["busy"] = o.pk in busy_adjacent  # только у смежных зон, без подробностей
        items.append(item)

    # стартовый вид — своя зона целиком (объект в контексте соседей), иначе свои объекты
    focus = (
        [home.geometry]
        if home is not None and home.geometry
        else [z["geometry"] for z in zones if z["mine"] and z["geometry"]]
        or [o["geometry"] for o in items if o["mine"] and o["geometry"]]
    )
    everything = [o["geometry"] for o in items if o["geometry"]] + [
        z["geometry"] for z in zones if z["geometry"]
    ]
    mine_items = [o for o in items if o["mine"]]
    summary = {
        "objects": len(mine_items),
        "unplaced": sum(1 for o in mine_items if not o["placed"]),
        "incidents": sum(o.get("incidents", 0) for o in mine_items),
        "escalated": sum(o.get("escalated", 0) for o in mine_items),
        "abnormal": sum(o.get("abnormal", 0) for o in mine_items),
        "silent": sum(o.get("silent", 0) for o in mine_items),
        "health_low": sum(o.get("health_low", 0) for o in mine_items),
        "orders": sum(o.get("orders", 0) for o in mine_items),
        "approvals": sum(o.get("approvals", 0) for o in mine_items),
        "overdue": sum(o.get("overdue", 0) for o in mine_items),
        "others": len(items) - len(mine_items),
    }
    return {
        "role": roles[0],
        "modes": modes,
        "mode": DEFAULT_MODE.get(roles[0], modes[0]) if DEFAULT_MODE.get(roles[0]) in modes else modes[0],
        "scope": user.scope_node.name if user.scope_node_id else "Все объекты",
        "global": has_global_scope(user),
        "home_zone": home.pk if home else None,
        "bbox": geo.bbox(focus) or geo.bbox(everything),
        "zones": zones,
        "objects": items,
        "incidents": incident_markers,
        "orders": order_markers,
        "summary": summary,
    }


def _kinds_under() -> list[str]:
    return [NodeKind.COMPLEX, NodeKind.CONTROL_HOUSE, NodeKind.GUARD_OBJECT, NodeKind.SECTION]


def others(user, *, page: int = 1, q: str = "") -> dict:
    """Объекты вне зоны ответственности — второстепенные, постранично: смежные зоны первыми."""
    home = _home_zone(user)
    adjacent = set(home.adjacent.values_list("pk", flat=True)) if home else set()
    zones = {z.path: z for z in Node.objects.filter(kind=NodeKind.ZONE)}
    rows = []
    own_node = _scope_check(user)
    for o in Node.objects.filter(kind=NodeKind.COMPLEX, is_active=True).order_by("name"):
        if own_node(o) or (q and q.lower() not in o.name.lower()):
            continue
        zone = None
        for length in range(Node.steplen, len(o.path), Node.steplen):
            zone = zones.get(o.path[:length], zone)
        rows.append(
            {
                "id": o.pk,
                "name": o.name,
                "zone": zone.pk if zone else None,
                "zone_name": zone.name if zone else "Без зоны",
                "adjacent": bool(zone and zone.pk in adjacent),
                "center": geo.centroid(o.geometry),
            }
        )
    rows.sort(key=lambda r: (not r["adjacent"], r["zone_name"], r["name"]))
    pager = Paginator(rows, PAGE)
    current = pager.get_page(page)
    return {"count": pager.count, "pages": pager.num_pages, "page": current.number, "results": list(current)}


def object_detail(user, obj: Node) -> dict:
    """Объект целиком — только в своей зоне: датчики на контуре, карточки, заявки, части."""
    zone = zone_of(obj)
    base = {
        "id": obj.pk,
        "name": obj.name,
        "zone": zone.pk if zone else None,
        "zone_name": zone.name if zone else None,
        "geometry": obj.geometry,
        "center": geo.centroid(obj.geometry),
        "mine": in_scope(user, obj),
    }
    if not base["mine"]:
        return {**base, "note": "Объект вне вашей зоны ответственности — подробности видит его зона."}
    modes = modes_for(user)
    channels = list(
        Channel.objects.filter(node__path__startswith=obj.path, is_active=True).select_related(
            "sensor_type", "node"
        )
    )
    ids = [c.pk for c in channels]
    states = dict(
        ChannelState.objects.filter(channel_id__in=ids, facet="primary").values_list("channel_id", "state")
    )
    health = {}
    if "health" in modes:
        health = {
            cid: (score, silent)
            for cid, score, silent in ChannelHealth.objects.filter(channel_id__in=ids).values_list(
                "channel_id", "score", "silent"
            )
        }
    risk: dict[int, str] = {}
    if "risk" in modes:
        for cid, level in ChannelRisk.objects.filter(channel_id__in=ids).values_list(
            "channel_id", "risk_level"
        ):
            risk[cid] = _max_level(risk.get(cid), level)
    pickets = [float(c.picket) for c in channels if c.picket is not None]
    lo, hi = (min(pickets), max(pickets)) if pickets else (0.0, 1.0)
    systems = sorted({c.sensor_type.system_type if c.sensor_type else "" for c in channels})
    sensors = []
    for c in channels:
        system = c.sensor_type.system_type if c.sensor_type else ""
        if c.location:
            position, placed = c.location, True
        else:
            t = (float(c.picket) - lo) / (hi - lo or 1) if c.picket is not None else 0.5
            lane = (systems.index(system) / max(len(systems) - 1, 1)) * 2 - 1 if len(systems) > 1 else 0
            position, placed = geo.along(obj.geometry, t, lane * 0.8), False
        score, silent = health.get(c.pk, (None, False))
        sensors.append(
            {
                "id": c.pk,
                "external_id": c.external_id,
                "name": c.name,
                "type": c.sensor_type.name if c.sensor_type else "",
                "system": system,
                "part": c.node.name if c.node_id != obj.pk else None,
                "state": states.get(c.pk, "unknown" if silent else "normal"),
                "silent": bool(silent),
                "health": score,
                "risk_level": risk.get(c.pk),
                "position": position,
                "placed": placed,
            }
        )
    incidents = []
    if "situation" in modes:
        incidents = [
            {
                "id": i.pk,
                "title": i.title,
                "type": i.get_type_display(),
                "severity": i.severity,
                "status": i.status,
                "status_display": i.get_status_display(),
                "assigned_to": (i.assigned_to.get_full_name() or i.assigned_to.username)
                if i.assigned_to
                else None,
                "escalation_level": i.escalation_level,
                "opened_at": i.opened_at,
            }
            for i in Incident.objects.filter(node__path__startswith=obj.path, status__in=OPEN)
            .select_related("assigned_to")
            .order_by("-priority")[:30]
        ]
    orders = []
    if "orders" in modes:
        now = timezone.now()
        orders = [
            {
                "id": o.pk,
                "number": o.number,
                "title": o.title,
                "status": o.status,
                "status_display": o.get_status_display(),
                "priority": o.priority,
                "due_at": o.due_at,
                "overdue": bool(o.due_at and o.due_at < now),
                "assignee": (o.assignee.get_full_name() or o.assignee.username) if o.assignee else None,
                "mine": o.assignee_id == user.pk,
            }
            for o in _orders_qs(user)
            .filter(node__path__startswith=obj.path)
            .select_related("assignee")
            .order_by("due_at")[:30]
        ]
    counts = Counter(s["state"] for s in sensors)
    return {
        **base,
        "criticality": obj.criticality,
        "parts": list(
            Node.objects.filter(path__startswith=obj.path, depth__gt=obj.depth).values("id", "name", "kind")
        ),
        "sensors": sensors,
        "states": dict(counts),
        "incidents": incidents,
        "orders": orders,
        "modes": modes,
    }
