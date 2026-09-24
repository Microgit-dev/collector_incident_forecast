"""
Чтение данных для признаков из БД: суточная витрина (вся история), оперативный контур
(скользящие последние 24 часа) и справочник каналов. COPY … TO STDOUT → Polars: миллионы строк
читаются за секунды, без Python-объектов на каждую строку.
"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta

import polars as pl
from django.db import connection

from apps.ingestion.history import EXCLUDED_YEARS

DAILY_SQL = """
SELECT channel_id, day, readings, warnings, alarms, faults, power_losses, unknowns, invalid, events,
       numeric_avg, numeric_min, numeric_max, last_state, first_fault_ts, last_ts
FROM telemetry_channeldaily
WHERE day >= %(since)s AND day < %(until)s {channels}
"""

# Последние 24 часа из оперативного контура в формате суточной строки
WINDOW_SQL = """
SELECT channel_id,
       count(*) AS readings,
       count(*) FILTER (WHERE state = 'warning') AS warnings,
       count(*) FILTER (WHERE state = 'alarm') AS alarms,
       count(*) FILTER (WHERE state = 'fault') AS faults,
       count(*) FILTER (WHERE state = 'power_loss') AS power_losses,
       count(*) FILTER (WHERE state = 'unknown') AS unknowns,
       count(*) FILTER (WHERE quality NOT IN ('ok', 'drift')) AS invalid,
       count(*) FILTER (WHERE state = 'event') AS events,
       avg(numeric) FILTER (WHERE quality IN ('ok', 'drift')) AS numeric_avg,
       min(numeric) FILTER (WHERE quality IN ('ok', 'drift')) AS numeric_min,
       max(numeric) FILTER (WHERE quality IN ('ok', 'drift')) AS numeric_max,
       coalesce((array_agg(state ORDER BY ts DESC) FILTER (WHERE facet = 'primary'))[1], '') AS last_state,
       min(ts) FILTER (WHERE state = 'fault') AS first_fault_ts,
       max(ts) AS last_ts
FROM telemetry_reading
WHERE ts > %(start)s AND ts <= %(end)s
GROUP BY channel_id
"""

META_SQL = """
SELECT c.id AS channel_id, c.node_id, coalesce(st.name, '?') AS sensor_type,
       coalesce(pr.value_kind, '') AS value_kind,
       (SELECT min(day) FROM telemetry_channeldaily d WHERE d.channel_id = c.id) AS first_day
FROM assets_channel c
LEFT JOIN assets_sensortype st ON st.id = c.sensor_type_id
LEFT JOIN normalization_sensorprofile pr ON pr.id = coalesce(c.profile_override_id, st.profile_id)
WHERE c.in_catalog AND c.is_active
"""

SCHEMA = {
    "channel_id": pl.Int64,
    "readings": pl.Int32,
    "warnings": pl.Int32,
    "alarms": pl.Int32,
    "faults": pl.Int32,
    "power_losses": pl.Int32,
    "unknowns": pl.Int32,
    "invalid": pl.Int32,
    "events": pl.Int32,
    "numeric_avg": pl.Float64,
    "numeric_min": pl.Float64,
    "numeric_max": pl.Float64,
    "last_state": pl.String,
}


def _query(sql: str, params: dict | None = None) -> pl.DataFrame:
    connection.ensure_connection()
    with connection.cursor() as cursor:
        # mogrify подставляет параметры на стороне клиента: COPY не принимает серверные параметры
        query = cursor.cursor.mogrify(sql, params or {})
    buffer = io.BytesIO()
    with (
        connection.connection.cursor() as raw,
        raw.copy(f"COPY ({query}) TO STDOUT (FORMAT csv, HEADER)") as copy,
    ):
        for chunk in copy:
            buffer.write(chunk)
    buffer.seek(0)
    if buffer.getbuffer().nbytes == 0:
        return pl.DataFrame()
    return pl.read_csv(
        buffer,
        try_parse_dates=True,
        schema_overrides=SCHEMA,
        null_values=[""],
        missing_utf8_is_empty_string=True,
    )


def excluded_range() -> tuple[date, date] | None:
    if not EXCLUDED_YEARS:
        return None
    return date(min(EXCLUDED_YEARS), 1, 1), date(max(EXCLUDED_YEARS), 12, 31)


def load_daily(since: date, until: date, channel_ids: list[int] | None = None) -> pl.DataFrame:
    channels = (
        f"AND channel_id = ANY(ARRAY[{','.join(map(str, channel_ids))}]::bigint[])" if channel_ids else ""
    )
    frame = _query(DAILY_SQL.format(channels=channels), {"since": since, "until": until})
    return _normalize(frame)


def load_window(end: datetime) -> pl.DataFrame:
    """Последние 24 часа до end как суточная строка с day = end.date()."""
    frame = _query(WINDOW_SQL, {"start": end - timedelta(hours=24), "end": end})
    if frame.is_empty():
        return frame
    from zoneinfo import ZoneInfo

    return _normalize(
        frame.with_columns(pl.lit(end.astimezone(ZoneInfo("Europe/Moscow")).date()).alias("day"))
    )


def _normalize(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty():
        return frame
    return frame.with_columns(
        pl.col("day").cast(pl.Date),
        pl.col("last_state").fill_null(""),
        pl.col("first_fault_ts").cast(pl.Datetime("us", "UTC"), strict=False),
        pl.col("last_ts").cast(pl.Datetime("us", "UTC"), strict=False),
    )


def load_weather() -> pl.DataFrame:
    """Суточная погода по Москве (Open-Meteo) для признаков подтопления."""
    from apps.integrations.models import WeatherDaily

    rows = list(
        WeatherDaily.objects.order_by("day").values_list(
            "day", "precipitation_mm", "temperature_max_c", "snow_depth_cm"
        )
    )
    return pl.DataFrame(
        rows,
        schema={
            "day": pl.Date,
            "precipitation_mm": pl.Float64,
            "temperature_max_c": pl.Float64,
            "snow_depth_cm": pl.Float64,
        },
        orient="row",
    )


def load_meta() -> pl.DataFrame:
    return _query(META_SQL).with_columns(pl.col("first_day").cast(pl.Date))


def node_daily(daily: pl.DataFrame, meta: pl.DataFrame) -> pl.DataFrame:
    """Неисправности и потери питания по объекту за сутки — признак каскада (связь, питание шкафа)."""
    return (
        daily.join(meta.select("channel_id", "node_id"), on="channel_id")
        .group_by("node_id", "day")
        .agg(pl.col("faults").sum().alias("node_faults"), pl.col("power_losses").sum().alias("node_power"))
    )


CONTINUITY_DAYS, CONTINUITY_MIN = 7, 6  # день «полный», если данные были в 6 из 7 последних суток
COVERAGE_SHARE = 0.2  # и каналов в нём не меньше 20 % от медианы


def data_clock() -> datetime | None:
    """
    «Текущее время данных», на которое строится прогноз.

    Живой поток (полные данные есть за вчера или сегодня) — текущий момент, но не позже последнего
    показания. Стенд на загруженной истории — конец последних полных суток. Одиночные сутки
    с горсткой каналов (тестовый прогон, ручная загрузка файла) полными не считаются:
    по ним признаки за 7–90 суток были бы пустыми.
    """
    from django.db.models import Max
    from django.utils import timezone

    from apps.telemetry.models import ChannelDaily, Reading

    day = last_complete_day()
    now = timezone.now()
    last_reading = Reading.objects.filter(ts__lte=now).aggregate(t=Max("ts"))["t"]
    if day is None:
        return min(last_reading, now) if last_reading else None
    today = timezone.localdate()
    if day >= today - timedelta(days=1) and last_reading:
        return min(last_reading, now)
    return ChannelDaily.objects.filter(day=day).aggregate(t=Max("last_ts"))["t"]


def last_complete_day() -> date | None:
    from django.db.models import Count, Max

    from apps.telemetry.models import ChannelDaily

    last = ChannelDaily.objects.aggregate(d=Max("day"))["d"]
    if last is None:
        return None
    counts = dict(
        ChannelDaily.objects.filter(day__gt=last - timedelta(days=400))
        .order_by()
        .values_list("day")
        .annotate(n=Count("channel"))
    )
    median = sorted(counts.values())[len(counts) // 2]
    for day in sorted(counts, reverse=True):
        window = [day - timedelta(days=k) for k in range(CONTINUITY_DAYS)]
        if counts[day] >= COVERAGE_SHARE * median and sum(d in counts for d in window) >= CONTINUITY_MIN:
            return day
    return None


NODE_DAILY_SQL = """
SELECT c.node_id, d.day, sum(d.faults)::int AS node_faults, sum(d.power_losses)::int AS node_power
FROM telemetry_channeldaily d JOIN assets_channel c ON c.id = d.channel_id
WHERE d.day >= %(since)s AND d.day < %(until)s
GROUP BY c.node_id, d.day
"""


def load_node_daily(since: date = date(2000, 1, 1), until: date = date(2100, 1, 1)) -> pl.DataFrame:
    """Объектные суточные счётчики по всем каналам объекта (и для обучения, и для прогноза)."""
    frame = _query(NODE_DAILY_SQL, {"since": since, "until": until})
    if frame.is_empty():
        return pl.DataFrame(
            schema={"node_id": pl.Int64, "day": pl.Date, "node_faults": pl.Int32, "node_power": pl.Int32}
        )
    return frame.with_columns(
        pl.col("day").cast(pl.Date), pl.col("node_faults").cast(pl.Int32), pl.col("node_power").cast(pl.Int32)
    )


def last_daily_day() -> date:
    with connection.cursor() as cursor:
        cursor.execute("SELECT max(day) FROM telemetry_channeldaily")
        return cursor.fetchone()[0]
