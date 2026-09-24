"""
Погода по Москве из Open-Meteo (открытый API без ключа, ТЗ §13) — только чтение.

- История: архив ERA5 (archive-api), суточные значения. Архив отстаёт от текущей даты на несколько суток.
- Последние дни и ближайшие сутки: прогнозный API (past_days + forecast_days); будущие сутки помечаются
  как прогноз и при следующей синхронизации заменяются фактом.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

import httpx
from django.conf import settings
from django.utils import timezone

from .clients import MOSCOW
from .models import WeatherDaily

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DAILY = "precipitation_sum,rain_sum,snowfall_sum,temperature_2m_mean,temperature_2m_max"
FIELDS = {
    "precipitation_sum": "precipitation_mm",
    "rain_sum": "rain_mm",
    "snowfall_sum": "snowfall_cm",
    "temperature_2m_mean": "temperature_mean_c",
    "temperature_2m_max": "temperature_max_c",
}
CHUNK_DAYS = 366


def _get(url: str, params: dict) -> dict:
    response = httpx.get(url, params={**MOSCOW, "timezone": "Europe/Moscow", **params}, timeout=60)
    response.raise_for_status()
    return response.json()


def _rows(payload: dict, snow_from_hourly: bool = False) -> dict[date, dict]:
    daily = payload["daily"]
    rows: dict[date, dict] = {}
    for i, day in enumerate(daily["time"]):
        rows[date.fromisoformat(day)] = {field: daily[key][i] for key, field in FIELDS.items()}
        if not snow_from_hourly and "snow_depth_mean" in daily:
            depth = daily["snow_depth_mean"][i]
            rows[date.fromisoformat(day)]["snow_depth_cm"] = depth * 100 if depth is not None else None
    if snow_from_hourly and "hourly" in payload:
        per_day = defaultdict(list)
        for ts, depth in zip(payload["hourly"]["time"], payload["hourly"]["snow_depth"], strict=True):
            if depth is not None:
                per_day[date.fromisoformat(ts[:10])].append(depth)
        for day, values in per_day.items():
            if day in rows:
                rows[day]["snow_depth_cm"] = round(100 * sum(values) / len(values), 1)
    return rows


def _save(rows: dict[date, dict], is_forecast_after: date | None = None) -> int:
    objs = [
        WeatherDaily(day=day, is_forecast=bool(is_forecast_after and day > is_forecast_after), **values)
        for day, values in rows.items()
    ]
    WeatherDaily.objects.bulk_create(
        objs,
        update_conflicts=True,
        unique_fields=["day"],
        update_fields=[*FIELDS.values(), "snow_depth_cm", "is_forecast", "updated_at"],
    )
    return len(objs)


def load_history(start: date, end: date, url: str | None = None) -> int:
    """Архив по годам (ограничение размера ответа), идемпотентно."""
    url = url or settings.INTEGRATIONS.get("WEATHER_URL") or ARCHIVE_URL
    saved, cursor = 0, start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS - 1), end)
        payload = _get(
            url,
            {
                "start_date": cursor.isoformat(),
                "end_date": chunk_end.isoformat(),
                "daily": f"{DAILY},snow_depth_mean",
            },
        )
        saved += _save(_rows(payload))
        cursor = chunk_end + timedelta(days=1)
    return saved


def sync_recent(past_days: int = 10, forecast_days: int = 3) -> int:
    """Последние сутки фактом и ближайшие прогнозом — для оперативного прогноза подтоплений."""
    payload = _get(
        FORECAST_URL,
        {"daily": DAILY, "hourly": "snow_depth", "past_days": past_days, "forecast_days": forecast_days},
    )
    return _save(_rows(payload, snow_from_hourly=True), is_forecast_after=timezone.localdate())
