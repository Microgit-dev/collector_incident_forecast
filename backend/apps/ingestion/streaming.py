"""
Публикация исторических событий в Kafka как живого потока: интервалы между событиями сохраняются
с ускорением, время по умолчанию заменяется текущим — реактивные правила отрабатывают как в работе.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.utils import timezone

from .adapters import REGISTRY
from .adapters.base import RawEvent
from .kafka import encode, make_producer


def stream_events(
    adapter: str,
    path: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    channels: list[int] | None = None,
    speed: float = 60.0,
    limit: int = 0,
    historical: bool = False,
    echo=None,
) -> int:
    events = REGISTRY[adapter].iter_events(path=path, start=start, end=end, channels=channels)
    return publish(events, speed=speed, limit=limit, historical=historical, echo=echo)


def publish(
    events: Iterable[RawEvent], *, speed: float = 60.0, limit: int = 0, historical: bool = False, echo=None
) -> int:
    producer = make_producer()
    topic = settings.KAFKA["TOPIC_RAW_EVENTS"]
    prev_ts = None
    sent = 0
    for event in events:
        if prev_ts is not None and speed > 0:
            gap = (event.ts - prev_ts).total_seconds() / speed
            if gap > 0:
                producer.poll(0)
                time.sleep(min(gap, 5.0))
        prev_ts = event.ts
        if not historical:
            event = dataclasses.replace(event, ts=timezone.now())
        # Ключ = канал: события одного канала попадают в одну партицию и сохраняют порядок
        producer.produce(topic, key=str(event.channel_external_id), value=encode(event.to_message()))
        sent += 1
        if echo and sent % 10_000 == 0:
            producer.poll(0)
            echo(f"sent {sent} (source time {prev_ts:%Y-%m-%d %H:%M:%S})")
        if limit and sent >= limit:
            break
    producer.flush()
    return sent


def states_before(path: str, moment: datetime, channels: list[int], lookback_days: int = 7) -> list[RawEvent]:
    """
    Последнее событие каждого канала (по каждому аспекту) до момента: с него эпизод начинается так же, как в тот день.
    Без этого повтор эпизода не дал бы переходов — каналы уже в том состоянии после прошлого показа.
    """
    import polars as pl

    moment = moment.astimezone(UTC)
    frame = (
        pl.scan_parquet(path)
        .filter(
            pl.col("channel_ext").is_in(channels)
            & (pl.col("ts") >= moment - timedelta(days=lookback_days))
            & (pl.col("ts") < moment)
        )
        .sort("ts")
        .group_by("channel_ext", "facet")  # основное состояние, работа насоса, охрана — по отдельности
        .last()
        .sort("ts")
        .select("event_id", "channel_ext", "ts", "raw_value", "raw_alarm")
        .collect()
    )
    return [
        RawEvent(
            event_id=row["event_id"],
            channel_external_id=row["channel_ext"],
            ts=row["ts"],
            raw_value=row["raw_value"] or "",
            raw_alarm=row["raw_alarm"],
        )
        for row in frame.iter_rows(named=True)
    ]
