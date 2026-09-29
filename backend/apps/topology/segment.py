"""
Выделение здания по спутниковому снимку (ИИ) с запасным путём через OpenStreetMap.

Сегментацию делает отдельный сервис infra/segmenter: Segment Anything (Meta, vit_b) на CPU получает
снимок Esri World Imagery вокруг рамки и возвращает контур самого заметного объекта внутри неё
(порт building_selector из проекта radar). Сервис тяжёлый (PyTorch, чекпойнт 375 МБ), поэтому
вынесен в профиль compose «ai»: без него бэкенд берёт контур из OpenStreetMap и честно пишет об этом.

Рамка подсказки: контур здания из векторной подложки под щелчком (он приходит с фронтенда),
расширенный на 15 %, или квадрат ±35 м вокруг точки. SAM не знает, что ищет именно здание:
рамка задаёт объект, и результат всегда показывается для проверки и правки вершин.
"""

from __future__ import annotations

import logging
import math

import httpx
from django.conf import settings

from . import geo

logger = logging.getLogger(__name__)
DEFAULT_HALF_M = 35.0
PAD = 0.15
MAX_SIDE_M = 400.0


def prompt_bbox(lon: float, lat: float, hint: dict | None) -> list[float]:
    """Рамка [min_lon, min_lat, max_lon, max_lat]: по контуру-подсказке или квадрат вокруг точки."""
    box = geo.bbox([hint]) if hint else None
    if box:
        w, s, e, n = box
        dx, dy = (e - w) * PAD, (n - s) * PAD
        box = [w - dx, s - dy, e + dx, n + dy]
    else:
        dlat = DEFAULT_HALF_M / 111_320
        dlon = DEFAULT_HALF_M / (111_320 * math.cos(math.radians(lat)))
        box = [lon - dlon, lat - dlat, lon + dlon, lat + dlat]
    side = max((box[2] - box[0]) * 111_320 * math.cos(math.radians(lat)), (box[3] - box[1]) * 111_320)
    if side > MAX_SIDE_M:
        raise geo.GeoError("Рамка больше 400 м — приблизьте карту и выделите одно здание")
    return [round(v, 7) for v in box]


def _polygon(feature: dict) -> dict | None:
    g = feature.get("geometry") or {}
    if g.get("type") != "Polygon":
        return None
    try:
        return geo.validate_polygon(g)
    except geo.GeoError:
        return None


def segment_building(lon: float, lat: float, hint: dict | None = None) -> dict:
    """
    Контур здания: {"geometry", "source", "score", "candidates", "area_m2", "center", ...}.
    source — "sam" (снимок, ИИ) или "osm:..." (запасной путь, note объясняет почему).
    """
    url = getattr(settings, "SEGMENTER_URL", "")
    note = "Сервис ИИ-выделения не подключён — контур взят из OpenStreetMap"
    if url:
        box = prompt_bbox(lon, lat, hint)
        try:
            response = httpx.post(f"{url.rstrip('/')}/api/extract-building", json={"bbox": box}, timeout=90)
            response.raise_for_status()
            body = response.json()
            candidates = [
                {"geometry": g, "score": round(float(c.get("score", 0)), 3)}
                for c in body.get("candidates", [])
                if (g := _polygon(c.get("feature", {})))
            ]
            if candidates:
                best = candidates[0]["geometry"]
                return {
                    "geometry": best,
                    "source": "sam",
                    "score": candidates[0]["score"],
                    "candidates": candidates,
                    "bbox": box,
                    "zoom": body.get("zoom_used"),
                    "name": "",
                    "address": "",
                    "levels": None,
                    "area_m2": round(geo.area_m2(best)),
                    "center": geo.centroid(best),
                    "exact": True,
                }
            note = "ИИ не нашёл контур в рамке — взят контур из OpenStreetMap"
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("segmenter failed: %s", exc)
            detail = ""
            if isinstance(exc, httpx.HTTPStatusError):
                try:
                    detail = exc.response.json().get("detail", "")
                except ValueError:
                    detail = ""
            note = (
                f"Сервис ИИ-выделения недоступен{': ' + detail if detail else ''} — контур из OpenStreetMap"
            )
    result = geo.detect_building(lon, lat)
    return {
        **result,
        "score": None,
        "candidates": [{"geometry": result["geometry"], "score": None}],
        "note": note,
    }
