"""
Управление структурой на карте: зоны ответственности, объекты, датчики, сотрудники, командирование.

Зона — узел дерева вида «зона» под районом; объекты зоны — её дочерние узлы. Поэтому всё, что уже
работает по поддереву (видимость данных, эскалация «объект → зона → район», кеши, отчёты), для зон
работает само: назначить сотрудника в зону = поставить зону его зоной ответственности.

Кто что может:
- зоны, их границы и смежность — право topology.manage_zones (руководитель, администратор);
- объекты и контуры — topology.add_node / change_node (руководитель, аналитик);
- датчики — assets.add_channel / change_channel (руководитель, аналитик);
- сотрудники и командирование — accounts.assign_staff (руководитель).
Всё — в пределах своей зоны ответственности (у районных ролей — весь район).
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.accounts.models import Secondment, User
from apps.assets.models import Channel, SensorType
from apps.notifications.services import notify

from . import geo
from .models import Node, NodeKind
from .selectors import has_global_scope, in_scope, zone_of

# Каналы, заведённые вручную, получают ид из отдельного диапазона: так их не спутать с каналами СМВУ
MANUAL_CHANNEL_BASE = 80_000_000
PALETTE = ["#1c7ed6", "#2f9e44", "#e8590c", "#9c36b5", "#0c8599", "#e03131", "#5c940d", "#f08c00"]
ADJACENT_M = 150  # зоны ближе этого считаются соседними при автоподборе


class StructureError(Exception):
    pass


def _check(user, perm: str, node: Node | None = None) -> None:
    if not user.has_perm(perm):
        raise StructureError("Недостаточно прав")
    if node is not None and not in_scope(user, node):
        raise StructureError("Узел вне вашей зоны ответственности")


def district_for(user) -> Node:
    """Район, в котором пользователь создаёт зоны: свой, у районных ролей — первый активный."""
    scope = user.scope_node
    if scope is not None:
        return Node.objects.get(path=scope.path[: Node.steplen])
    district = Node.objects.filter(depth=1, is_active=True, kind=NodeKind.DISTRICT).order_by("path").first()
    if district is None:
        raise StructureError("Нет района")
    return district


def zones_for(user):
    qs = Node.objects.filter(kind=NodeKind.ZONE).order_by("name")
    if has_global_scope(user):
        return qs
    scope = user.scope_node
    if scope is None:
        return qs.none()
    # руководитель зоны видит свою зону и соседей своего района (для смежности и командирования)
    return qs.filter(path__startswith=scope.path[: Node.steplen])


# ---------- зоны ----------


@transaction.atomic
def create_zone(user, *, name: str, geometry: dict | None, color: str = "") -> Node:
    _check(user, "topology.manage_zones")
    district = district_for(user)
    if not has_global_scope(user) and user.scope_node.depth > 1:
        raise StructureError("Создавать зоны может руководитель района")
    if not name.strip():
        raise StructureError("Укажите название зоны")
    if Node.objects.filter(kind=NodeKind.ZONE, name=name.strip(), path__startswith=district.path).exists():
        raise StructureError("Зона с таким названием уже есть")
    used = Node.objects.filter(kind=NodeKind.ZONE).count()
    zone = Node.objects.get(pk=district.pk).add_child(
        kind=NodeKind.ZONE,
        name=name.strip(),
        geometry=geo.validate_polygon(geometry) if geometry else None,
        geometry_source="manual" if geometry else "",
        color=color or PALETTE[used % len(PALETTE)],
    )
    if zone.geometry:
        zone.adjacent.set(suggest_adjacent(zone))
    return zone


@transaction.atomic
def update_zone(user, zone: Node, data: dict) -> Node:
    _check(user, "topology.manage_zones", zone)
    if zone.kind != NodeKind.ZONE:
        raise StructureError("Это не зона")
    if "name" in data and data["name"].strip():
        zone.name = data["name"].strip()
    if "color" in data:
        zone.color = data["color"] or zone.color
    if data.get("geometry"):
        zone.geometry = geo.validate_polygon(data["geometry"])
        zone.geometry_source = "manual"
    zone.save()
    if "adjacent" in data:
        allowed = zones_for(user).exclude(pk=zone.pk)
        zone.adjacent.set(allowed.filter(pk__in=[int(i) for i in data["adjacent"]]))
    return zone


def suggest_adjacent(zone: Node) -> list[Node]:
    """Соседи по карте: контуры касаются или ближе ADJACENT_M метров."""
    return [
        z
        for z in Node.objects.filter(kind=NodeKind.ZONE).exclude(pk=zone.pk).exclude(geometry=None)
        if geo.distance_m(zone.geometry, z.geometry) <= ADJACENT_M
    ]


# ---------- объекты ----------


def _target_zone(user, parent_id) -> Node:
    parent = Node.objects.filter(pk=parent_id).first() if parent_id else None
    if parent is None:
        raise StructureError("Выберите зону")
    if parent.kind not in (NodeKind.ZONE, NodeKind.DISTRICT):
        raise StructureError("Объект создаётся в зоне или районе")
    _check(user, "topology.add_node", parent)
    return parent


@transaction.atomic
def create_object(
    user, *, parent_id, name: str, geometry: dict, criticality: int = 3, source: str = ""
) -> Node:
    parent = _target_zone(user, parent_id)
    if not name.strip():
        raise StructureError("Укажите название объекта")
    polygon = geo.validate_polygon(geometry)
    center = geo.centroid(polygon)
    warning = ""
    if parent.kind == NodeKind.ZONE and parent.geometry and not geo.contains(parent.geometry, *center):
        warning = "Контур объекта вне границы зоны"
    obj = Node.objects.get(pk=parent.pk).add_child(
        kind=NodeKind.COMPLEX,
        name=name.strip(),
        geometry=polygon,
        geometry_source=source or "manual",
        criticality=max(1, min(int(criticality or 3), 5)),
    )
    obj.warning = warning
    return obj


@transaction.atomic
def update_object(user, obj: Node, data: dict) -> Node:
    _check(user, "topology.change_node", obj)
    if "name" in data and data["name"].strip():
        obj.name = data["name"].strip()
    if "criticality" in data:
        obj.criticality = max(1, min(int(data["criticality"]), 5))
    if data.get("geometry"):
        obj.geometry = geo.validate_polygon(data["geometry"])
        obj.geometry_source = data.get("source") or "manual"
    obj.save()
    if data.get("zone") and int(data["zone"]) != (zone_of(obj).pk if zone_of(obj) else None):
        move_object(user, obj, int(data["zone"]))
        obj.refresh_from_db()
    return obj


@transaction.atomic
def move_object(user, obj: Node, zone_id: int) -> Node:
    """Перенос объекта в другую зону (со всеми частями, датчиками и карточками — они на поддереве)."""
    _check(user, "topology.change_node", obj)
    target = _target_zone(user, zone_id)
    if target.pk == obj.pk or target.path.startswith(obj.path):
        raise StructureError("Нельзя перенести объект внутрь самого себя")
    Node.objects.get(pk=obj.pk).move(Node.objects.get(pk=target.pk), pos="sorted-child")
    return Node.objects.get(pk=obj.pk)


# ---------- датчики ----------


def next_channel_id() -> int:
    top = Channel.objects.filter(external_id__gte=MANUAL_CHANNEL_BASE).aggregate(m=Max("external_id"))["m"]
    return (top or MANUAL_CHANNEL_BASE) + 1


@transaction.atomic
def create_sensor(user, *, node_id, name: str, sensor_type_id=None, picket=None, location=None) -> Channel:
    node = Node.objects.filter(pk=node_id).first()
    if node is None:
        raise StructureError("Выберите объект или зону")
    _check(user, "assets.add_channel", node)
    if not name.strip():
        raise StructureError("Укажите название датчика")
    sensor_type = SensorType.objects.filter(pk=sensor_type_id).first() if sensor_type_id else None
    point = _point(location)
    return Channel.objects.create(
        external_id=next_channel_id(),
        node=node,
        name=name.strip(),
        sensor_type=sensor_type,
        tag=sensor_type.system_type if sensor_type else "",
        picket=picket if picket not in ("", None) else None,
        location=point,
        in_catalog=False,
    )


def _point(location) -> list[float] | None:
    if not location:
        return None
    try:
        lon, lat = float(location[0]), float(location[1])
    except (TypeError, ValueError, IndexError) as exc:
        raise StructureError("Неверная точка датчика") from exc
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise StructureError("Неверная точка датчика")
    return [round(lon, 7), round(lat, 7)]


@transaction.atomic
def attach_sensor(user, channel: Channel, *, node_id=None, location=None) -> Channel:
    """Прикрепить датчик к другому объекту или зоне и/или поставить его точку на карте."""
    _check(user, "assets.change_channel", channel.node)
    if node_id:
        target = Node.objects.filter(pk=node_id).first()
        if target is None:
            raise StructureError("Нет такого узла")
        _check(user, "assets.change_channel", target)
        channel.node = target
    if location is not None:
        channel.location = _point(location)
    channel.save(update_fields=["node", "location", "updated_at"])
    return channel


# ---------- сотрудники ----------


def staff_for(user):
    """Сотрудники, которых руководитель может назначать: в его зоне ответственности (у района — все)."""
    qs = (
        User.objects.filter(is_active=True)
        .exclude(username="training.bot")
        .select_related("scope_node", "team")
    )
    if has_global_scope(user):
        return qs
    scope = user.scope_node
    return qs.filter(scope_node__path__startswith=scope.path[: Node.steplen]) if scope else qs.none()


@transaction.atomic
def assign(user, employee: User, node_id) -> User:
    _check(user, "accounts.assign_staff")
    if not staff_for(user).filter(pk=employee.pk).exists():
        raise StructureError("Сотрудник не из вашей зоны")
    target = Node.objects.filter(pk=node_id).first()
    if target is None:
        raise StructureError("Нет такой зоны")
    _check(user, "accounts.assign_staff", target)
    employee.scope_node = target
    employee.save(update_fields=["scope_node"])
    notify(
        [employee],
        title=f"Ваша зона ответственности: {target.name}",
        body=f"Назначил(а): {user.get_full_name() or user.username}.",
        link="/",
    )
    return employee


def is_adjacent(a: Node | None, b: Node) -> bool:
    return a is not None and (a.pk == b.pk or a.adjacent.filter(pk=b.pk).exists())


@transaction.atomic
def second(
    user, employee: User, *, zone_id, hours: float, reason: str = "", emergency: bool = False
) -> Secondment:
    """Командировать сотрудника в другую зону: в смежную — обычно, в несмежную — только «крайний случай»."""
    _check(user, "accounts.assign_staff")
    if not staff_for(user).filter(pk=employee.pk).exists():
        raise StructureError("Сотрудник не из вашей зоны")
    zone = Node.objects.filter(pk=zone_id, kind=NodeKind.ZONE).first()
    if zone is None:
        raise StructureError("Выберите зону")
    home = zone_of(employee.scope_node) if employee.scope_node else None
    if home is not None and home.pk == zone.pk:
        raise StructureError("Сотрудник уже работает в этой зоне")
    adjacent = is_adjacent(home, zone)
    if not adjacent:
        if not emergency:
            raise StructureError(
                "Зона не смежная с зоной сотрудника — отметьте «крайний случай» и укажите причину"
            )
        if not reason.strip():
            raise StructureError("Для крайнего случая нужна причина")
    hours = max(0.5, min(float(hours or 8), 72))
    now = timezone.now()
    record = Secondment.objects.create(
        user=employee,
        zone=zone,
        starts_at=now,
        ends_at=now + timedelta(hours=hours),
        reason=reason.strip()[:255],
        emergency=not adjacent,
        created_by=user,
    )
    notify(
        [employee],
        title=f"Вы направлены в зону «{zone.name}» на {hours:g} ч",
        body=(f"Причина: {record.reason}. " if record.reason else "")
        + "Карточки и уведомления зоны видны вам до "
        + timezone.localtime(record.ends_at).strftime("%d.%m %H:%M")
        + (". Крайний случай: зона не смежная." if record.emergency else "."),
        level="high" if record.emergency else "medium",
        link="/",
    )
    return record


def recall(user, record: Secondment) -> Secondment:
    _check(user, "accounts.assign_staff", record.zone)
    if record.cancelled_at is None and record.ends_at > timezone.now():
        record.cancelled_at = timezone.now()
        record.save(update_fields=["cancelled_at"])
        notify([record.user], title=f"Командирование в зону «{record.zone.name}» завершено", link="/")
    return record


def active_secondments(user):
    now = timezone.now()
    qs = Secondment.objects.filter(cancelled_at__isnull=True, ends_at__gt=now).select_related(
        "user", "zone", "created_by"
    )
    if has_global_scope(user):
        return qs
    scope = user.scope_node
    district = scope.path[: Node.steplen] if scope else "-"
    return qs.filter(zone__path__startswith=district)
