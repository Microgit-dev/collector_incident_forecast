"""Read an immutable offline snapshot without PostgreSQL or the running application stack."""

import hashlib
import json
from datetime import timedelta
from functools import cached_property
from pathlib import Path

import polars as pl

from . import data


class ParquetHistory:
    def __init__(self, folder: Path):
        self.folder = folder.resolve()
        self.manifest = json.loads((self.folder / "manifest.json").read_text())
        self.years = sorted(int(y) for y in self.manifest["years"])
        self.paths = [self.folder / "daily" / f"daily_{year}.parquet" for year in self.years]
        if not self.paths or not all(p.is_file() for p in self.paths):
            raise ValueError("Snapshot has no complete daily files")
        provenance = (self.folder / "manifest.json").read_bytes() + (
            self.folder / "channels.parquet"
        ).read_bytes()
        self.cache_key = hashlib.sha256(provenance).hexdigest()[:20]

    def _scan(self):
        return pl.scan_parquet(self.paths)

    @cached_property
    def meta(self):
        first = self._scan().group_by("channel_id").agg(pl.col("day").min().alias("first_day"))
        return pl.scan_parquet(self.folder / "channels.parquet").join(first, on="channel_id").collect()

    def load_meta(self):
        return self.meta

    def load_daily(self, since, until, channel_ids=None):
        frame = self._scan().filter((pl.col("day") >= since) & (pl.col("day") < until))
        if channel_ids is not None:
            frame = frame.filter(pl.col("channel_id").is_in(channel_ids))
        return data._normalize(frame.collect(engine="streaming"))

    @cached_property
    def nodes(self):
        return (
            self._scan()
            .join(self.meta.lazy().select("channel_id", "node_id"), on="channel_id")
            .group_by("node_id", "day")
            .agg(
                pl.col("faults").sum().cast(pl.Int32).alias("node_faults"),
                pl.col("power_losses").sum().cast(pl.Int32).alias("node_power"),
            )
            .collect(engine="streaming")
        )

    def load_node_daily(self):
        return self.nodes

    def excluded_range(self):
        return data.excluded_range()

    @cached_property
    def coverage(self):
        return dict(self._scan().group_by("day").agg(pl.len()).collect().iter_rows())

    def last_daily_day(self):
        return max(self.coverage)

    def last_complete_day(self):
        last = self.last_daily_day()
        counts = {d: n for d, n in self.coverage.items() if d > last - timedelta(days=400)}
        median = sorted(counts.values())[len(counts) // 2]
        for day in sorted(counts, reverse=True):
            if (
                counts[day] >= data.COVERAGE_SHARE * median
                and sum(day - timedelta(days=k) in counts for k in range(data.CONTINUITY_DAYS))
                >= data.CONTINUITY_MIN
            ):
                return day
        return None

    def load_weather(self):
        # First baselines intentionally omit weather. No reconstruction of forecast vintages.
        return pl.DataFrame(
            schema={
                "day": pl.Date,
                "precipitation_mm": pl.Float64,
                "temperature_max_c": pl.Float64,
                "snow_depth_cm": pl.Float64,
            }
        )
