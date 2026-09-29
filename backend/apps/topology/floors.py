"""
Этажи объекта и планы помещений: загрузка плана, контрольные точки, привязка к местности.

Порядок работы в редакторе:
1. Контур здания — автовыделение по снимку (ИИ, segment.py) или по OpenStreetMap, правка вершин.
2. Контрольный этаж: план подгоняется под контур («по контуру»), затем уточняется парами точек
   «угол на плане ↔ угол на снимке».
3. Остальные этажи: точки ставятся на плане этажа и на плане контрольного — план ложится на него.
4. Датчики ставятся на этаж точкой на его плане (Channel.floor + location).

Права — как у объекта: правка контура и этажей — topology.change_node в своей зоне ответственности.
"""

from __future__ import annotations

from django.db import transaction
from PIL import Image, UnidentifiedImageError

from . import georef
from .models import Floor, Node, NodeKind
from .selectors import in_scope

MAX_PLAN_BYTES = 25 * 1024 * 1024
MAX_PLAN_SIDE = 16000
PLAN_FORMATS = {"PNG", "JPEG", "WEBP", "GIF", "BMP"}


class FloorError(Exception):
    pass


def check(user, node: Node) -> None:
    if not user.has_perm("topology.change_node"):
        raise FloorError("Недостаточно прав")
    if not in_scope(user, node):
        raise FloorError("Объект вне вашей зоны ответственности")


def floor_dict(f: Floor) -> dict:
    stamp = int(f.updated_at.timestamp()) if f.updated_at else 0
    return {
        "id": f.pk,
        "node": f.node_id,
        "level": f.level,
        "name": f.name,
        "title": f.title,
        "is_base": f.is_base,
        "plan": f"/topology/floors/{f.pk}/plan/?v={stamp}" if f.plan else None,
        "width": f.plan_width,
        "height": f.plan_height,
        "points": f.points or [],
        "corners": f.corners,
        "rmse_m": f.rmse_m,
        "opacity": f.opacity,
        "sensors": f.channels.count(),
    }


def floors_of(node: Node) -> list[Floor]:
    return list(Floor.objects.filter(node=node).order_by("level"))


def _read_plan(upload) -> tuple[int, int]:
    if upload.size > MAX_PLAN_BYTES:
        raise FloorError("План больше 25 МБ — сохраните его в PNG или JPEG меньшего размера")
    try:
        with Image.open(upload) as image:
            fmt = image.format
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise FloorError("Файл плана не читается как изображение (нужен PNG, JPEG или WEBP)") from exc
    finally:
        upload.seek(0)
    if fmt not in PLAN_FORMATS:
        raise FloorError("План — изображение PNG, JPEG или WEBP")
    if max(width, height) > MAX_PLAN_SIDE:
        raise FloorError(f"План больше {MAX_PLAN_SIDE} px по стороне — уменьшите разрешение")
    return width, height


def _refit(floor: Floor) -> None:
    """Пересчёт углов по точкам; точек мало — план остаётся непривязанным."""
    usable = [p for p in floor.points if p.get("on", True)]
    if not floor.plan_width or len(usable) < georef.MIN_POINTS:
        floor.corners, floor.rmse_m = None, None
        return
    result = georef.fit(floor.points, floor.plan_width, floor.plan_height)
    floor.corners = result.corners(floor.plan_width, floor.plan_height)
    floor.rmse_m = result.rmse_m


@transaction.atomic
def create_floor(user, node: Node, *, level, name: str = "", plan=None) -> Floor:
    if node.kind != NodeKind.COMPLEX:
        raise FloorError("Этажи бывают у объекта")
    check(user, node)
    try:
        level = int(level)
    except (TypeError, ValueError) as exc:
        raise FloorError("Укажите номер этажа") from exc
    if not -10 <= level <= 150:
        raise FloorError("Номер этажа от −10 до 150")
    if Floor.objects.filter(node=node, level=level).exists():
        raise FloorError("Такой этаж у объекта уже есть")
    floor = Floor(node=node, level=level, name=(name or "").strip()[:64])
    # первый этаж с планом — контрольный: к нему привязываются остальные
    floor.is_base = not Floor.objects.filter(node=node, is_base=True).exists()
    if plan is not None:
        floor.plan_width, floor.plan_height = _read_plan(plan)
        floor.plan = plan
    floor.save()
    return floor


@transaction.atomic
def update_floor(user, floor: Floor, data: dict, plan=None) -> Floor:
    check(user, floor.node)
    if "name" in data:
        floor.name = (data.get("name") or "").strip()[:64]
    if "level" in data and str(data["level"]) != str(floor.level):
        try:
            level = int(data["level"])
        except (TypeError, ValueError) as exc:
            raise FloorError("Номер этажа — целое число") from exc
        if Floor.objects.filter(node=floor.node_id, level=level).exclude(pk=floor.pk).exists():
            raise FloorError("Такой этаж у объекта уже есть")
        floor.level = level
    if "opacity" in data:
        floor.opacity = max(0.1, min(float(data["opacity"]), 1.0))
    if plan is not None:
        width, height = _read_plan(plan)
        if floor.plan:
            floor.plan.delete(save=False)
        # другой лист — прежние точки к нему не относятся, если размер не совпал
        if (width, height) != (floor.plan_width, floor.plan_height):
            floor.points = []
        floor.plan, floor.plan_width, floor.plan_height = plan, width, height
    if "points" in data:
        try:
            floor.points = georef.clean_points(data["points"])
        except georef.GeorefError as exc:
            raise FloorError(str(exc)) from exc
    if "points" in data or plan is not None:
        try:
            _refit(floor)
        except georef.GeorefError as exc:
            raise FloorError(str(exc)) from exc
    if data.get("is_base") and not floor.is_base:
        Floor.objects.filter(node=floor.node_id, is_base=True).update(is_base=False)
        floor.is_base = True
    floor.save()
    return floor


@transaction.atomic
def delete_floor(user, floor: Floor) -> None:
    check(user, floor.node)
    node_id, was_base = floor.node_id, floor.is_base
    if floor.plan:
        floor.plan.delete(save=False)
    floor.delete()
    if was_base:
        # контрольным становится ближайший к земле из оставшихся
        rest = Floor.objects.filter(node=node_id).order_by("level")
        nearest = min(rest, key=lambda f: (abs(f.level - 1), f.level), default=None)
        if nearest:
            Floor.objects.filter(pk=nearest.pk).update(is_base=True)
