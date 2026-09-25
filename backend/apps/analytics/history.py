"""
Режим просмотра истории: показания канала и состояние объекта за выбранный период.

Источники: оперативный контур (hypertable) — с его начала, Parquet-архив по годам — раньше, суточная
витрина — за всю историю. Период до месяца показывается по сырым показаниям (длинный ряд сжимается
до ~600 точек: минимум, среднее, максимум в интервале), длиннее — по суткам. Поверх показаний —
карточки и решения того времени, прогнозы по каналу и заявки.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl
from django.conf import settings
from django.db import connection
from django.db.models import Min, Q

from apps.assets.models import Channel
from apps.forecasting.models import Prediction
from apps.incidents.models import Incident
from apps.telemetry.models import ChannelDaily, Reading
from apps.topology.models import Node

MSK = ZoneInfo("Europe/Moscow")
MAX_RAW = timedelta(days=31)
MAX_SPAN = timedelta(days=3 * 366)
TARGET_POINTS = 600
MAX_INTERVALS = 3000
BUCKETS = [60, 300, 900, 1800, 3600, 3 * 3600, 6 * 3600, 12 * 3600, 86400]  # секунды
VALID = ("ok", "drift")
WORST = ["alarm", "fault", "power_loss", "unknown", "normal"]

FIELDS = ("ts", "state", "raw_value", "numeric", "facet", "quality")
SCHEMA = {
    "ts": pl.Datetime("us", "UTC"),
    "state": pl.String,
    "raw_value": pl.String,
    "numeric": pl.Float64,
    "facet": pl.String,
    "quality": pl.String,
}


class HistoryError(Exception):
    pass


def period(since: date, until: date) -> tuple[datetime, datetime]:
    """Сутки по Москве включительно → полуинтервал в UTC."""
    start = datetime.combine(since, datetime.min.time(), MSK)
    end = datetime.combine(until, datetime.min.time(), MSK) + timedelta(days=1)
    if end <= start:
        raise HistoryError("Конец периода раньше начала")
    if end - start > MAX_SPAN:
        raise HistoryError("Период — не больше трёх лет")
    return start.astimezone(UTC), end.astimezone(UTC)


def _operational_start() -> datetime | None:
    return Reading.objects.aggregate(first=Min("ts"))["first"]


def _frame(rows) -> pl.DataFrame:
    return pl.DataFrame(list(rows), schema=SCHEMA, orient="row")


def _operational(channel_id: int, start: datetime, end: datetime) -> pl.DataFrame:
    return _frame(
        Reading.objects.filter(channel_id=channel_id, ts__gte=start, ts__lt=end)
        .order_by("ts")
        .values_list(*FIELDS)
    )


def _seed(channel_id: int, start: datetime) -> pl.DataFrame:
    """Последнее сообщение каждого аспекта до начала периода — с какого состояния период начался."""
    window = Reading.objects.filter(channel_id=channel_id, ts__lt=start, ts__gte=start - timedelta(days=7))
    rows = []
    for facet in window.values_list("facet", flat=True).distinct():
        last = window.filter(facet=facet).order_by("-ts").values_list(*FIELDS).first()
        if last:
            rows.append(last)
    return _frame(rows)


def _archive(channel_id: int, start: datetime, end: datetime) -> tuple[pl.DataFrame, list[str]]:
    frames, used = [], []
    for year in range(start.astimezone(MSK).year, end.astimezone(MSK).year + 1):
        path = settings.ARTIFACTS_DIR / "archive" / f"journal_{year}.parquet"
        if not path.exists():
            continue
        frames.append(
            pl.scan_parquet(path)
            .filter((pl.col("channel_id") == channel_id) & (pl.col("ts") >= start) & (pl.col("ts") < end))
            .select(list(SCHEMA))
            .collect()
        )
        used.append(str(year))
    return (pl.concat(frames) if frames else pl.DataFrame(schema=SCHEMA)), used


def raw_readings(channel_id: int, start: datetime, end: datetime) -> tuple[pl.DataFrame, list[str]]:
    """Показания за период: до начала оперативного контура — из архива, дальше — из hypertable."""
    oldest = _operational_start()
    parts, sources = [], []
    if oldest is None or start < oldest:
        frame, years = _archive(channel_id, start, min(end, oldest) if oldest else end)
        parts.append(frame)
        if years:
            sources.append("архив " + ", ".join(years))
    if oldest is not None and end > oldest:
        parts.append(_operational(channel_id, max(start, oldest), end))
        sources.append("оперативный контур")
    frame = pl.concat(parts).sort("ts") if parts else pl.DataFrame(schema=SCHEMA)
    return frame, sources


def _bucket(span: timedelta, points: int) -> int:
    need = span.total_seconds() / TARGET_POINTS
    return next((b for b in BUCKETS if b >= need), BUCKETS[-1]) if points > TARGET_POINTS else 0


def _numeric(frame: pl.DataFrame, span: timedelta) -> tuple[list[dict], int]:
    values = frame.filter(pl.col("numeric").is_not_null() & pl.col("quality").is_in(VALID)).select(
        "ts", "numeric"
    )
    bucket = _bucket(span, values.height)
    if not bucket:
        return [{"t": ts, "v": v} for ts, v in values.iter_rows()], 0
    agg = (
        values.sort("ts")
        .group_by_dynamic("ts", every=f"{bucket}s")
        .agg(
            pl.col("numeric").min().alias("min"),
            pl.col("numeric").mean().alias("avg"),
            pl.col("numeric").max().alias("max"),
        )
    )
    return [
        {"t": ts, "min": round(lo, 3), "v": round(avg, 3), "max": round(hi, 3)}
        for ts, lo, avg, hi in agg.iter_rows()
    ], bucket


def _intervals(
    frame: pl.DataFrame, seed: pl.DataFrame, start: datetime, end: datetime
) -> dict[str, list[dict]]:
    """Смены состояния по аспектам (основное, питание, работа, охрана) как интервалы."""
    out: dict[str, list[dict]] = {}
    both = pl.concat([seed, frame]).filter(pl.col("state") != "event") if seed.height else frame
    facets = [f for f, _ in Counter(both["facet"].to_list()).most_common(4)] if both.height else []
    for facet in facets:
        rows = both.filter(pl.col("facet") == facet).select("ts", "state", "raw_value").sort("ts")
        runs: list[dict] = []
        for ts, state, raw in rows.iter_rows():
            ts = max(ts, start)
            if runs and runs[-1]["state"] == state:
                continue
            if runs:
                runs[-1]["to"] = ts
            runs.append({"from": ts, "to": end, "state": state, "raw": raw})
        out[facet] = [r for r in runs if r["to"] > r["from"]][-MAX_INTERVALS:]
    return out


def _incidents(q: Q, start: datetime, end: datetime, limit: int = 60) -> list[dict]:
    rows = (
        Incident.objects.filter(q, opened_at__lt=end)
        .filter(Q(resolved_at__isnull=True) | Q(resolved_at__gte=start))
        .select_related("node", "assigned_to")
        .prefetch_related("decisions__decided_by")
        .distinct()
        .order_by("opened_at")[:limit]
    )
    out = []
    for i in rows:
        decision = max(i.decisions.all(), key=lambda d: d.decided_at, default=None)
        out.append(
            {
                "id": i.pk,
                "title": i.title,
                "type": i.type,
                "severity": i.severity,
                "status": i.status,
                "is_forecast": i.is_forecast,
                "is_emulated": i.is_emulated,
                "opened_at": i.opened_at,
                "resolved_at": i.resolved_at,
                "node": i.node.name,
                "assigned_to": i.assigned_to.get_full_name() if i.assigned_to else None,
                "decision": {
                    "outcome": decision.get_outcome_display(),
                    "cause": decision.get_cause_display() if decision.cause else None,
                    "by": decision.decided_by.get_full_name() if decision.decided_by else None,
                    "at": decision.decided_at,
                }
                if decision
                else None,
            }
        )
    return out


def _daily(channel_ids: list[int], start: datetime, end: datetime):
    return ChannelDaily.objects.filter(
        channel_id__in=channel_ids,
        day__gte=start.astimezone(MSK).date(),
        day__lt=(end - timedelta(microseconds=1)).astimezone(MSK).date() + timedelta(days=1),
    )


def channel_history(channel: Channel, start: datetime, end: datetime) -> dict:
    span = end - start
    daily = list(
        _daily([channel.pk], start, end)
        .order_by("day")
        .values(
            "day",
            "readings",
            "normal",
            "warnings",
            "alarms",
            "faults",
            "power_losses",
            "unknowns",
            "events",
            "invalid",
            "numeric_avg",
            "numeric_min",
            "numeric_max",
            "last_state",
        )
    )
    profile = channel.profile
    result = {
        "channel": {
            "id": channel.pk,
            "external_id": channel.external_id,
            "name": channel.name,
            "node": channel.node.name,
            "node_id": channel.node_id,
            "sensor_type": channel.sensor_type.name if channel.sensor_type else "",
            "picket": float(channel.picket) if channel.picket is not None else None,
            "unit": getattr(profile, "unit", "") or "",
            "warn": getattr(profile, "warn_threshold", None),
            "alarm": getattr(profile, "alarm_threshold", None),
        },
        "period": {"from": start, "to": end},
        "daily": daily,
        "resolution": "daily",
        "numeric": [],
        "bucket_s": None,
        "states": {},
        "invalid": [],
        "sources": ["суточная витрина"],
        "readings": sum(d["readings"] for d in daily),
    }
    if span <= MAX_RAW:
        frame, sources = raw_readings(channel.pk, start, end)
        seed = _seed(channel.pk, start)
        numeric, bucket = _numeric(frame, span)
        invalid = frame.filter(~pl.col("quality").is_in(VALID))
        result.update(
            resolution="bucket" if bucket else "raw",
            numeric=numeric,
            bucket_s=bucket or None,
            states=_intervals(frame, seed, start, end),
            invalid=[
                {"t": ts, "quality": q, "raw": raw}
                for ts, q, raw in invalid.select("ts", "quality", "raw_value").head(300).iter_rows()
            ],
            invalid_total=invalid.height,
            sources=sources or ["нет показаний за период"],
            readings=frame.height,
        )
    result["incidents"] = _incidents(Q(alerts__channel=channel), start, end)
    result["node_incidents"] = [
        i
        for i in _incidents(Q(node=channel.node), start, end, limit=30)
        if i["id"] not in {x["id"] for x in result["incidents"]}
    ]
    predictions = Prediction.objects.filter(
        channel=channel, issued_at__gte=start, issued_at__lt=end, is_backtest=False
    )
    result["predictions"] = [
        {"t": ts, "task": task, "p": round(p, 3), "level": level, "outcome": outcome}
        for ts, task, p, level, outcome in predictions.order_by("issued_at").values_list(
            "issued_at", "task", "probability", "risk_level", "outcome"
        )[:TARGET_POINTS]
    ]
    return result


def _worst(row: dict) -> str | None:
    if not row["readings"]:
        return None
    for state, field in (
        ("alarm", "alarms"),
        ("fault", "faults"),
        ("power_loss", "power_losses"),
        ("unknown", "unknowns"),
    ):
        if row[field]:
            return state
    return "normal"


def node_history(node: Node, start: datetime, end: datetime, limit: int = 60) -> dict:
    """Объект за период по суткам: худшее состояние каждого канала в каждые сутки и итоги по дням."""
    channels = {
        c.pk: c
        for c in Channel.objects.filter(node__path__startswith=node.path).select_related(
            "sensor_type", "node"
        )
    }
    days = []
    day = start.astimezone(MSK).date()
    last = (end - timedelta(seconds=1)).astimezone(MSK).date()
    while day <= last:
        days.append(day)
        day += timedelta(days=1)
    cells: dict[int, dict[str, str]] = defaultdict(dict)
    totals: dict[str, Counter] = defaultdict(Counter)
    for row in _daily(list(channels), start, end).values(
        "channel_id", "day", "readings", "alarms", "faults", "power_losses", "unknowns"
    ):
        state = _worst(row)
        key = row["day"].isoformat()
        if state:
            cells[row["channel_id"]][key] = state
            totals[key]["reporting"] += 1
            totals[key][state] += 1
    ranked = sorted(
        cells,
        key=lambda cid: (
            -sum(1 for s in cells[cid].values() if s != "normal"),
            channels[cid].name,
        ),
    )
    silent = len(channels) - len(cells)
    return {
        "node": {"id": node.pk, "name": node.name, "channels": len(channels)},
        "period": {"from": start, "to": end},
        "days": [d.isoformat() for d in days],
        "totals": [{"day": d.isoformat(), **totals[d.isoformat()]} for d in days],
        "rows": [
            {
                "channel": cid,
                "name": channels[cid].name,
                "sensor_type": channels[cid].sensor_type.name if channels[cid].sensor_type else "",
                "object": channels[cid].node.name,
                "abnormal_days": sum(1 for s in cells[cid].values() if s != "normal"),
                "cells": cells[cid],
            }
            for cid in ranked[:limit]
        ],
        "shown": min(limit, len(ranked)),
        "reporting": len(cells),
        "silent": silent,
        "incidents": _incidents(Q(node__path__startswith=node.path), start, end, limit=100),
    }


def coverage() -> dict:
    """Какие периоды есть: архив по годам, суточная витрина, оперативный контур."""
    archive = sorted(
        int(p.stem.split("_")[1])
        for p in (settings.ARTIFACTS_DIR / "archive").glob("journal_*.parquet")
        if p.stem.split("_")[1].isdigit()
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT min(day), max(day) FROM telemetry_channeldaily")
        daily = cursor.fetchone()
    oldest = _operational_start()
    return {
        "archive_years": archive,
        "daily": {"from": daily[0], "to": daily[1]} if daily[0] else None,
        "operational_from": oldest,
        "max_raw_days": MAX_RAW.days,
    }
