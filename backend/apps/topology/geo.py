"""
Геометрия на карте (WGS84, GeoJSON [долгота, широта]) и автовыделение здания.

Контуры — полигоны зданий и зон, поэтому хватает простых функций в локальной плоской проекции
(равнопромежуточная у центра, погрешность на масштабе района — доли процента): центр, площадь,
точка в полигоне, расстояние между контурами. Отдельная ГИС-библиотека не нужна.

Автовыделение здания: запрос к Overpass API (OpenStreetMap) «здания в радиусе N метров от точки»,
выбирается здание, внутри которого точка, иначе ближайшее. Это внешний запрос только на чтение, он
передаёт лишь координату щелчка; адрес сервиса настраивается (OVERPASS_URL), пустой — автовыделение
выключено и контур обводится вручную.
"""

from __future__ import annotations

import logging
import math

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)
R = 6_371_000.0


class GeoError(Exception):
    pass


def map_config() -> dict:
    """Подложки карт интерфейса: векторная светлая и тёмная, спутниковая (растровые тайлы)."""
    return {
        "light": settings.MAP_STYLE_LIGHT,
        "dark": settings.MAP_STYLE_DARK,
        "satellite": settings.MAP_SATELLITE_TILES,
        "satellite_attribution": settings.MAP_SATELLITE_ATTRIBUTION,
    }


# ---------- проекция и простые меры ----------


def _xy(lon: float, lat: float, lat0: float) -> tuple[float, float]:
    return math.radians(lon) * R * math.cos(math.radians(lat0)), math.radians(lat) * R


def ring(geometry: dict | None) -> list[list[float]]:
    """Внешнее кольцо полигона (или мультиполигона — первого)."""
    if not geometry:
        return []
    if geometry["type"] == "Polygon":
        return geometry["coordinates"][0]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"][0][0]
    if geometry["type"] == "Point":
        return [geometry["coordinates"]]
    return []


def centroid(geometry: dict | None) -> list[float] | None:
    pts = ring(geometry)
    if not pts:
        return None
    if len(pts) < 3:
        return [pts[0][0], pts[0][1]]
    lat0 = pts[0][1]
    xy = [_xy(lon, lat, lat0) for lon, lat in pts]
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1], strict=False):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(a) < 1e-9:
        return [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]
    cx, cy = cx / (3 * a), cy / (3 * a)
    return [math.degrees(cx / (R * math.cos(math.radians(lat0)))), math.degrees(cy / R)]


def area_m2(geometry: dict | None) -> float:
    pts = ring(geometry)
    if len(pts) < 3:
        return 0.0
    lat0 = pts[0][1]
    xy = [_xy(lon, lat, lat0) for lon, lat in pts]
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1], strict=False))) / 2


def contains(geometry: dict | None, lon: float, lat: float) -> bool:
    pts = ring(geometry)
    inside = False
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1], strict=False):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1 + 1e-15) + x1:
            inside = not inside
    return inside


def _seg_dist(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy + 1e-12)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def distance_m(g1: dict | None, g2: dict | None) -> float:
    """Кратчайшее расстояние между контурами; 0 — пересекаются или касаются."""
    a, b = ring(g1), ring(g2)
    if not a or not b:
        return math.inf
    if any(contains(g2, *p) for p in a) or any(contains(g1, *p) for p in b):
        return 0.0
    lat0 = a[0][1]
    pa = [_xy(*p, lat0) for p in a]
    pb = [_xy(*p, lat0) for p in b]
    best = math.inf
    for p in pa:
        for s, e in zip(pb, pb[1:] + pb[:1], strict=False):
            best = min(best, _seg_dist(p, s, e))
    for p in pb:
        for s, e in zip(pa, pa[1:] + pa[:1], strict=False):
            best = min(best, _seg_dist(p, s, e))
    return best


def bbox(geometries: list[dict]) -> list[float] | None:
    pts = [p for g in geometries for p in ring(g)]
    if not pts:
        return None
    return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]


def validate_polygon(geometry: dict) -> dict:
    """Проверка контура из редактора: замкнутое кольцо из 3+ точек в разумных координатах."""
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise GeoError("Контур должен быть полигоном")
    try:
        pts = [[round(float(lon), 7), round(float(lat), 7)] for lon, lat in geometry["coordinates"][0]]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise GeoError("Неверные координаты контура") from exc
    if pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    if len(pts) < 4:
        raise GeoError("В контуре меньше трёх точек")
    if len(pts) > 2000:
        raise GeoError("Слишком сложный контур")
    if not all(-180 <= lon <= 180 and -90 <= lat <= 90 for lon, lat in pts):
        raise GeoError("Координаты вне допустимого диапазона")
    return {"type": "Polygon", "coordinates": [pts]}


def along(geometry: dict | None, t: float, lane: float = 0.0) -> list[float] | None:
    """
    Точка на главной оси контура: t ∈ [0, 1] вдоль, lane ∈ [-1, 1] поперёк (доля полуширины).
    Так датчики без своих координат раскладываются по зданию по пикету — схематично, но на объекте.
    """
    pts = ring(geometry)
    if len(pts) < 3:
        return centroid(geometry)
    lat0 = pts[0][1]
    xy = [_xy(*p, lat0) for p in pts[:-1] if p] or [_xy(*pts[0], lat0)]
    c = _xy(*centroid(geometry), lat0)
    # главная ось — направление на самую дальнюю от центра вершину
    far = max(xy, key=lambda p: math.hypot(p[0] - c[0], p[1] - c[1]))
    ang = math.atan2(far[1] - c[1], far[0] - c[0])
    ux, uy = math.cos(ang), math.sin(ang)
    proj = [(p[0] - c[0]) * ux + (p[1] - c[1]) * uy for p in xy]
    side = [-(p[0] - c[0]) * uy + (p[1] - c[1]) * ux for p in xy]
    lo, hi = min(proj), max(proj)
    half = max(abs(min(side)), abs(max(side))) * 0.6
    d = lo + (hi - lo) * (0.1 + 0.8 * max(0.0, min(1.0, t)))
    x = c[0] + d * ux - lane * half * uy
    y = c[1] + d * uy + lane * half * ux
    return [math.degrees(x / (R * math.cos(math.radians(lat0)))), math.degrees(y / R)]


# ---------- здания OpenStreetMap ----------


def _overpass(query: str) -> list[dict]:
    url = getattr(settings, "OVERPASS_URL", "")
    if not url:
        raise GeoError(
            "Автовыделение выключено (нет адреса картографического сервиса) — обведите контур вручную"
        )
    try:
        response = httpx.post(
            url, data={"data": query}, timeout=25, headers={"User-Agent": "collector-forecast/1.0"}
        )
        response.raise_for_status()
        return response.json().get("elements", [])
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("overpass failed: %s", exc)
        raise GeoError("Картографический сервис недоступен — обведите контур вручную") from exc


def _polygon(element: dict) -> dict | None:
    geometry = element.get("geometry")
    if not geometry or len(geometry) < 4:
        return None
    pts = [[round(p["lon"], 7), round(p["lat"], 7)] for p in geometry]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return {"type": "Polygon", "coordinates": [pts]}


def _building(element: dict, geometry: dict) -> dict:
    tags = element.get("tags", {})
    address = " ".join(x for x in (tags.get("addr:street", ""), tags.get("addr:housenumber", "")) if x)
    return {
        "geometry": geometry,
        "source": f"osm:way/{element['id']}",
        "name": tags.get("name", ""),
        "address": address,
        "levels": tags.get("building:levels"),
        "area_m2": round(area_m2(geometry)),
        "center": centroid(geometry),
    }


def detect_building(lon: float, lat: float, radius: int = 40) -> dict:
    """Здание под точкой щелчка (или ближайшее в радиусе) — предложение контура для нового объекта."""
    key = f"geo:building:{lon:.5f}:{lat:.5f}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    elements = _overpass(f"[out:json][timeout:20];way(around:{radius},{lat},{lon})[building];out tags geom;")
    candidates = [(e, g) for e in elements if (g := _polygon(e))]
    if not candidates:
        raise GeoError("Здание рядом с точкой не найдено — обведите контур вручную")
    point = {"type": "Point", "coordinates": [lon, lat]}
    inside = [(e, g) for e, g in candidates if contains(g, lon, lat)]
    element, geometry = (
        min(inside, key=lambda eg: area_m2(eg[1]))
        if inside
        else min(candidates, key=lambda eg: distance_m(eg[1], point))
    )
    result = _building(element, geometry)
    result["exact"] = bool(inside)
    cache.set(key, result, 86400)
    return result


def buildings_in(south: float, west: float, north: float, east: float, limit: int = 2000) -> list[dict]:
    """Здания в прямоугольнике — для демо-привязки объектов (seed_geo)."""
    elements = _overpass(
        f"[out:json][timeout:60];way({south},{west},{north},{east})[building];out tags geom {limit};"
    )
    return [_building(e, g) for e in elements if (g := _polygon(e))]
