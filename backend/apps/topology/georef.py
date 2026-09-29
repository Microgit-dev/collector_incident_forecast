"""
Привязка плана этажа к местности по контрольным точкам.

Контрольная точка — пара «пиксель плана (px, py) ↔ точка на местности (lon, lat)». По трём и больше
точкам подбирается аффинное преобразование пиксель → веб-меркатор методом наименьших квадратов
(как GDAL order 1). Подгонка идёт в метрах веб-меркатора, а не в градусах: на широте Москвы градус
долготы вдвое короче градуса широты, и подгонка в градусах перекашивает план.

Результат — четыре угла исходной картинки в WGS84: их ест MapLibre ImageSource (nw, ne, se, sw).
Аффинного преобразования для плана здания достаточно: план — чертёж в масштабе, без перспективы.

Этажи выше контрольного привязываются к нему: точка, отмеченная на плане контрольного этажа,
пересчитывается в координаты его преобразованием (to_lonlat), и дальше этаж подгоняется так же.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

R = 6378137.0
MAX_LAT = 85.05
MIN_POINTS = 3
MAX_POINTS = 40
# Почти коллинеарные точки (все вдоль одной стены) дают устойчивое на вид, но ложное решение:
# требуем разброс поперёк главной оси не меньше 0,5 % размера плана
MIN_SPREAD = 5e-3


class GeorefError(Exception):
    pass


def merc(lon: float, lat: float) -> tuple[float, float]:
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def unmerc(x: float, y: float) -> tuple[float, float]:
    return math.degrees(x / R), math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2)


@dataclass(frozen=True)
class Fit:
    """Преобразование пиксель → веб-меркатор: x = a·u + b·v + c, y = d·u + e·v + f (u, v — пиксели / масштаб)."""

    coef_x: tuple[float, float, float]
    coef_y: tuple[float, float, float]
    scale: float
    rmse_m: float
    used: int

    def to_lonlat(self, px: float, py: float) -> tuple[float, float]:
        u, v = px / self.scale, py / self.scale
        a, b, c = self.coef_x
        d, e, f = self.coef_y
        return unmerc(a * u + b * v + c, d * u + e * v + f)

    def corners(self, width: int, height: int) -> list[list[float]]:
        """Углы картинки nw, ne, se, sw в WGS84 (порядок MapLibre ImageSource)."""
        return [
            [round(c, 7) for c in self.to_lonlat(x, y)]
            for x, y in ((0, 0), (width, 0), (width, height), (0, height))
        ]


def clean_points(points: list) -> list[dict]:
    """Точки из редактора: число, диапазоны, флаг «включена». Порядок сохраняется."""
    if not isinstance(points, list):
        raise GeorefError("Контрольные точки — список")
    if len(points) > MAX_POINTS:
        raise GeorefError(f"Не больше {MAX_POINTS} контрольных точек")
    out = []
    for raw in points:
        try:
            p = {k: float(raw[k]) for k in ("px", "py", "lon", "lat")}
        except (KeyError, TypeError, ValueError) as exc:
            raise GeorefError("У контрольной точки нужны px, py, lon, lat") from exc
        if not (-180 <= p["lon"] <= 180 and -MAX_LAT <= p["lat"] <= MAX_LAT):
            raise GeorefError("Координаты контрольной точки вне допустимого диапазона")
        if p["px"] < 0 or p["py"] < 0:
            raise GeorefError("Пиксель контрольной точки вне плана")
        p = {k: round(v, 7 if k in ("lon", "lat") else 2) for k, v in p.items()}
        p["on"] = bool(raw.get("on", True))
        out.append(p)
    return out


def fit(points: list[dict], width: int, height: int) -> Fit:
    """МНК-подгонка по включённым точкам. GeorefError — точек мало или они на одной линии."""
    used = [p for p in points if p.get("on", True)]
    if len(used) < MIN_POINTS:
        raise GeorefError(f"Нужно не меньше {MIN_POINTS} включённых контрольных точек")
    scale = float(max(width, height, 1))
    uv = np.array([[p["px"] / scale, p["py"] / scale] for p in used])
    centered = uv - uv.mean(axis=0)
    spread = math.sqrt(max(float(np.linalg.eigvalsh(centered.T @ centered / len(used))[0]), 0.0))
    if spread < MIN_SPREAD:
        raise GeorefError("Контрольные точки почти на одной линии — добавьте точку в стороне")
    xy = np.array([merc(p["lon"], p["lat"]) for p in used])
    design = np.column_stack([uv, np.ones(len(used))])
    # центрируем меркатор: абсолютные значения ~10⁶ м съедают точность решения
    origin = xy.mean(axis=0)
    sol_x, *_ = np.linalg.lstsq(design, xy[:, 0] - origin[0], rcond=None)
    sol_y, *_ = np.linalg.lstsq(design, xy[:, 1] - origin[1], rcond=None)
    pred = design @ np.column_stack([sol_x, sol_y]) + origin
    # метры меркатора растянуты в 1/cos(широта) раз — невязку переводим в метры на местности
    k = math.cos(math.radians(used[0]["lat"]))
    rmse = float(np.sqrt(np.mean(np.sum((pred - xy) ** 2, axis=1)))) * k
    return Fit(
        coef_x=(float(sol_x[0]), float(sol_x[1]), float(sol_x[2] + origin[0])),
        coef_y=(float(sol_y[0]), float(sol_y[1]), float(sol_y[2] + origin[1])),
        scale=scale,
        rmse_m=round(rmse, 2),
        used=len(used),
    )
