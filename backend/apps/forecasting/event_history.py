"""Observed telemetry episodes, distinct from confirmed physical incidents and daily labels."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

KEYS = ["channel_id", "facet", "segment"]
TIME = pl.Datetime("us", "UTC")
RUN_SCHEMA = {
    "channel_id": pl.Int64,
    "facet": pl.String,
    "segment": pl.Int32,
    "start_at": TIME,
    "last_at": TIME,
    "event": pl.Boolean,
    "observations": pl.UInt32,
}
EPISODE_SCHEMA = {
    "episode_id": pl.String,
    "channel_id": pl.Int64,
    "node_id": pl.Int64,
    "sensor_type": pl.String,
    "start_at": TIME,
    "end_bound": TIME,
    "last_at": TIME,
    "left_censored": pl.Boolean,
    "right_censored": pl.Boolean,
    "facets": pl.String,
    "observations": pl.Int64,
}


def observations(raw, task):
    """Same event predicates as the training labels; aspects retain independent states."""
    if task == "gas":
        raw = raw.filter(pl.col("quality").is_in(["ok", "drift"]) & pl.col("numeric").is_not_null())
        event = pl.col("numeric") >= 1.0
    elif task == "flood":
        event = pl.col("state") == "alarm"
    elif task == "sensor_failure":
        event = pl.col("state") == "fault"
    else:
        raise ValueError(f"Unknown task: {task}")
    return raw.select("channel_id", "facet", "ts", event.alias("event"))


def event_days(frame):
    return (
        frame.filter(pl.col("event"))
        .with_columns(pl.col("ts").dt.convert_time_zone("Europe/Moscow").dt.date().alias("day"))
        .group_by("channel_id", "day")
        .agg(
            pl.len().alias("event_rows"),
            pl.col("ts").min().alias("first_at"),
            pl.col("ts").max().alias("last_at"),
        )
    )


def compress_observations(frame, segment):
    """Collapse identical Boolean states; a positive wins conflicting values at one timestamp."""
    keys = ["channel_id", "facet"]
    return (
        frame.sort([*keys, "ts", "event"])
        .unique(subset=[*keys, "ts"], keep="last", maintain_order=True)
        .with_columns(
            (pl.col("event") != pl.col("event").shift(1).over(keys))
            .fill_null(True)
            .cast(pl.UInt32)
            .alias("_new")
        )
        .with_columns(pl.col("_new").cum_sum().over(keys).alias("_run"))
        .group_by([*keys, "_run"])
        .agg(
            pl.col("ts").min().alias("start_at"),
            pl.col("ts").max().alias("last_at"),
            pl.col("event").first(),
            pl.len().alias("observations"),
        )
        .with_columns(pl.lit(segment, dtype=pl.Int32).alias("segment"))
        .select(list(RUN_SCHEMA))
    )


def merge_runs(runs):
    """Annual extraction must not invent a new onset at January 1; excluded years do reset state."""
    return (
        runs.sort([*KEYS, "start_at"])
        .with_columns(
            (pl.col("event") != pl.col("event").shift(1).over(KEYS))
            .fill_null(True)
            .cast(pl.UInt32)
            .alias("_new")
        )
        .with_columns(pl.col("_new").cum_sum().over(KEYS).alias("_run"))
        .group_by([*KEYS, "_run"])
        .agg(
            pl.col("start_at").min(),
            pl.col("last_at").max(),
            pl.col("event").first(),
            pl.col("observations").sum(),
        )
        .sort([*KEYS, "start_at"])
    )


def episodes_from_runs(runs, meta, segment_ends, task, gap_minutes=30, cutoff=None):
    if gap_minutes < 0:
        raise ValueError("Episode gap must be nonnegative")
    if cutoff is not None:
        # Summaries may span a fold boundary. Keep only state information observed by cutoff.
        # For a spanning run, its first observation is an exact known lower bound on count/last.
        runs = runs.filter(pl.col("start_at") < cutoff).with_columns(
            pl.when(pl.col("last_at") >= cutoff)
            .then(1)
            .otherwise(pl.col("observations"))
            .cast(pl.UInt32)
            .alias("observations"),
            pl.when(pl.col("last_at") >= cutoff)
            .then(pl.col("start_at"))
            .otherwise(pl.col("last_at"))
            .alias("last_at"),
        )
        segment_ends = {segment: min(end, cutoff) for segment, end in segment_ends.items()}
    timeline = (
        merge_runs(runs)
        .with_columns(
            pl.col("event").shift(1).over(KEYS).is_null().alias("left_censored"),
            pl.col("start_at").shift(-1).over(KEYS).alias("end_at"),
        )
        .filter(pl.col("event"))
        .sort("channel_id", "segment", "start_at", "facet")
    )
    catalog = {r["channel_id"]: r for r in meta.iter_rows(named=True)}
    records, current = [], None

    def finish(row):
        identifier = f"{task}:{row['channel_id']}:{row['start_at'].isoformat()}:{row['facets']}"
        row["episode_id"] = hashlib.sha256(identifier.encode()).hexdigest()[:24]
        return row

    current_segment = None
    for row in timeline.iter_rows(named=True):
        bound = row["end_at"] or segment_ends[row["segment"]]
        new = {
            "channel_id": row["channel_id"],
            "start_at": row["start_at"],
            "end_bound": bound,
            "last_at": row["last_at"],
            "left_censored": row["left_censored"],
            "right_censored": row["end_at"] is None,
            "facets": row["facet"],
            "observations": row["observations"],
            "node_id": catalog[row["channel_id"]]["node_id"],
            "sensor_type": catalog[row["channel_id"]]["sensor_type"],
        }
        separate = (
            current is None
            or current["channel_id"] != row["channel_id"]
            or current_segment != row["segment"]
            or new["start_at"] > current["end_bound"] + timedelta(minutes=gap_minutes)
        )
        if separate:
            if current is not None:
                records.append(finish(current))
            current, current_segment = new, row["segment"]
        else:
            current["end_bound"] = max(current["end_bound"], new["end_bound"])
            current["last_at"] = max(current["last_at"], new["last_at"])
            current["left_censored"] |= new["left_censored"]
            current["right_censored"] |= new["right_censored"]
            current["facets"] = ",".join(sorted(set(current["facets"].split(",")) | {new["facets"]}))
            current["observations"] += new["observations"]
    if current is not None:
        records.append(finish(current))
    return pl.DataFrame(records, schema=EPISODE_SCHEMA) if records else pl.DataFrame(schema=EPISODE_SCHEMA)


def prepare_events(source, output, specs, through=2025, progress=print):
    """Extract immutable event-day facts and state runs. No 2026 rows enter H09."""
    years = [year for year in source.years if year <= through]
    segments, segment = {}, 0
    for i, year in enumerate(years):
        if i and year != years[i - 1] + 1:
            segment += 1
        segments[year] = segment
    ends = {
        seg: datetime(year + 1, 1, 1, tzinfo=ZoneInfo("Europe/Moscow")).astimezone(UTC)
        for year, seg in segments.items()
    }
    config = {
        "snapshot_fingerprint": source.cache_key,
        "years": years,
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "tasks": [spec.task for spec in specs],
        "segments": segments,
    }
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "manifest.json"
    if manifest.exists() and json.loads(manifest.read_text()) != json.loads(json.dumps(config)):
        raise ValueError("Event cache snapshot, extractor or tasks changed")
    manifest.write_text(json.dumps(config, indent=2))
    meta = source.load_meta()
    for spec in specs:
        selected_meta = (
            meta.filter(pl.col("sensor_type").is_in(spec.sensor_types)) if spec.sensor_types else meta
        )
        ids = selected_meta["channel_id"].implode()
        for year in years:
            days_path, runs_path = (
                output / f"{spec.task}_{year}_days.parquet",
                output / f"{spec.task}_{year}_runs.parquet",
            )
            if days_path.exists() and runs_path.exists():
                continue
            progress(f"[{spec.task}/{year}] extracting event facts and state runs")
            raw = pl.scan_parquet(source.folder / "archive" / f"journal_{year}.parquet").filter(
                pl.col("channel_id").is_in(ids)
            )
            obs = observations(raw, spec.task)
            days = event_days(obs).collect(engine="streaming")
            expected = (
                pl.scan_parquet(source.folder / "daily" / f"daily_{year}.parquet")
                .filter(pl.col("channel_id").is_in(ids) & spec.event().fill_null(False))
                .select("channel_id", "day")
                .collect()
                .sort("channel_id", "day")
            )
            if not days.select("channel_id", "day").sort("channel_id", "day").equals(expected):
                raise ValueError(f"{spec.task}/{year}: raw events disagree with daily labels")
            runs = compress_observations(obs, segments[year]).collect(engine="streaming")
            for target, frame in [(days_path, days), (runs_path, runs)]:
                temporary = target.with_suffix(".tmp")
                frame.write_parquet(temporary)
                temporary.replace(target)
            progress(f"[{spec.task}/{year}] {len(days):,} positive days; {len(runs):,} state runs")
    return config, ends
