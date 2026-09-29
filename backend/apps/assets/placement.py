"""
Где рисовать датчик на карте: своя точка (поставлена в редакторе или на плане этажа) или, если её нет,
место на контуре объекта по пикету — вдоль главной оси здания, подсистемы разнесены поперёк.
Общий расчёт для карты мониторинга и маршрута нарушителя, чтобы датчик был в одном и том же месте.
"""

from __future__ import annotations

from apps.topology import geo


def positions(geometry: dict | None, channels) -> dict[int, tuple[list[float] | None, bool]]:
    """ид канала → (точка [lon, lat], поставлена ли вручную)."""
    channels = list(channels)
    pickets = [float(c.picket) for c in channels if c.picket is not None]
    lo, hi = (min(pickets), max(pickets)) if pickets else (0.0, 1.0)
    systems = sorted({c.sensor_type.system_type if c.sensor_type else "" for c in channels})
    out = {}
    for c in channels:
        if c.location:
            out[c.pk] = (c.location, True)
            continue
        system = c.sensor_type.system_type if c.sensor_type else ""
        t = (float(c.picket) - lo) / (hi - lo or 1) if c.picket is not None else 0.5
        lane = (systems.index(system) / max(len(systems) - 1, 1)) * 2 - 1 if len(systems) > 1 else 0
        out[c.pk] = (geo.along(geometry, t, lane * 0.8), False)
    return out
