"""H03 features at MSK midnight: windows are [as_of-hours, as_of), never the target day."""

import hashlib
import json
from pathlib import Path

import polars as pl

COUNTS = {
    "warnings": "warning",
    "alarms": "alarm",
    "faults": "fault",
    "power": "power_loss",
    "unknown": "unknown",
}
COUNT_COLUMNS = [f"short_{name}_{h}h" for h in (1, 6) for name in ("readings", *COUNTS)]
FEATURES = [
    *COUNT_COLUMNS,
    *[f"short_num_{stat}_{h}h" for h in (1, 6) for stat in ("avg", "max", "range")],
    "short_readings_fraction_1h",
    "short_readings_fraction_6h",
    "short_num_change_1h_6h",
    "short_staleness_hours",
]


def aggregate_windows(events: pl.LazyFrame) -> pl.LazyFrame:
    """One row per observed channel/day. Count all facets, as in the existing daily table."""
    local = pl.col("ts").dt.convert_time_zone("Europe/Moscow")
    hour = local.dt.hour()
    numeric = pl.when(pl.col("quality").is_in(["ok", "drift"])).then(pl.col("numeric"))
    aggregates = [
        pl.len().alias("control_readings_24h"),
        (pl.col("state") == "fault").sum().alias("control_faults_24h"),
        (pl.col("state") == "alarm").sum().alias("control_alarms_24h"),
        numeric.mean().alias("control_numeric_avg_24h"),
    ]
    # Seconds since the latest message to the next midnight, including seconds/fractions.
    seconds = (
        local.dt.hour() * 3600.0 + local.dt.minute() * 60.0 + local.dt.second() + local.dt.microsecond() / 1e6
    )
    aggregates.append(((86400.0 - seconds.max()) / 3600.0).alias("short_staleness_hours"))
    for hours in (1, 6):
        inside = hour >= 24 - hours
        value = numeric.filter(inside)
        aggregates.extend(
            [
                inside.sum().alias(f"short_readings_{hours}h"),
                *[
                    ((pl.col("state") == state) & inside).sum().alias(f"short_{name}_{hours}h")
                    for name, state in COUNTS.items()
                ],
                value.mean().alias(f"short_num_avg_{hours}h"),
                value.max().alias(f"short_num_max_{hours}h"),
                (value.max() - value.min()).alias(f"short_num_range_{hours}h"),
            ]
        )
    return (
        events.filter(pl.col("channel_id").is_not_null())
        .with_columns(local.dt.date().alias("day"))
        .group_by("channel_id", "day")
        .agg(aggregates)
        .with_columns(
            *[
                (pl.col(f"short_readings_{h}h") / pl.col("control_readings_24h")).alias(
                    f"short_readings_fraction_{h}h"
                )
                for h in (1, 6)
            ],
            (pl.col("short_num_avg_1h") - pl.col("short_num_avg_6h")).alias("short_num_change_1h_6h"),
        )
    )


def prepare_windows(source, output: Path, progress=print):
    """Reusable versioned cache; each year is written atomically after successful extraction."""
    code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    config = {"snapshot_fingerprint": source.cache_key, "code_sha256": code_hash, "windows_hours": [1, 6, 24]}
    manifest = output / "manifest.json"
    output.mkdir(parents=True, exist_ok=True)
    if manifest.exists() and json.loads(manifest.read_text()) != config:
        raise ValueError("Short-window cache belongs to a different snapshot or extractor")
    manifest.write_text(json.dumps(config, indent=2))
    for year in source.years:
        target = output / f"short_{year}.parquet"
        if target.exists():
            continue
        progress(f"[short windows] extracting {year}")
        frame = aggregate_windows(
            pl.scan_parquet(source.folder / "archive" / f"journal_{year}.parquet")
        ).collect(engine="streaming")
        temporary = target.with_suffix(".tmp")
        frame.write_parquet(temporary)
        temporary.replace(target)
        progress(f"[short windows] {year}: {len(frame):,} channel-days")
    return config


def attach_windows(frame: pl.DataFrame, windows: pl.DataFrame) -> pl.DataFrame:
    """Preserve the reference rows/labels; silent days have zero counts and missing numerics."""
    joined = frame.join(windows, on=["channel_id", "day"], how="left", validate="m:1", maintain_order="left")
    for daily, control in [("readings_1", "readings"), ("faults_1", "faults")]:
        if (
            daily in joined.columns
            and joined.filter(pl.col(daily) != pl.col(f"control_{control}_24h").fill_null(0)).height
        ):
            raise ValueError(f"24-hour control disagrees with daily feature: {daily}")
    return joined.with_columns(
        pl.col(COUNT_COLUMNS).fill_null(0),
        pl.col("short_readings_fraction_1h", "short_readings_fraction_6h").fill_null(0),
    )
