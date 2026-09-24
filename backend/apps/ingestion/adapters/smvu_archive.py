"""
Нормализованный архив журналов (Parquet) как источник событий для воспроизведения.

Годовой CSV — это гигабайты и десятки миллионов строк: чтобы проиграть один час каскада,
его пришлось бы читать целиком. Архив фильтруется по времени за секунды и отдаёт исходные
сырые значения, поэтому поток проходит ту же нормализацию, что и живой.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import polars as pl

from .base import RawEvent


class SmvuArchiveAdapter:
    key = "smvu_archive"

    def iter_events(
        self, *, path: str, start: datetime | None = None, end: datetime | None = None, **_
    ) -> Iterator[RawEvent]:
        lf = pl.scan_parquet(path)
        if start is not None:
            lf = lf.filter(pl.col("ts") >= start)
        if end is not None:
            lf = lf.filter(pl.col("ts") < end)
        frame = (
            lf.select("event_id", "channel_ext", "ts", "raw_value", "raw_alarm")
            .unique(subset=["event_id", "channel_ext", "ts", "raw_value"])
            .sort("ts", "event_id")
            .collect()
        )
        for row in frame.iter_rows(named=True):
            yield RawEvent(
                event_id=row["event_id"],
                channel_external_id=row["channel_ext"],
                ts=row["ts"],
                raw_value=row["raw_value"] or "",
                raw_alarm=row["raw_alarm"],
            )
