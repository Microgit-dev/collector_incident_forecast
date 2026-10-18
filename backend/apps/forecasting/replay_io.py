"""Reuse H09's frozen event opportunities without reconstructing labels for each policy study."""

import json

import polars as pl

from .event_history import EPISODE_SCHEMA
from .event_replay import ReplayContext


def load_frozen_replay(reference, events_run, year, task, part, meta):
    predictions = pl.read_parquet(reference / str(year) / f"{task}_{part}_predictions.parquet")
    opportunities = pl.read_parquet(events_run / str(year) / f"{task}_{part}_episode_opportunities.parquet")
    days = pl.read_parquet(events_run / f"{task}_event_days.parquet")
    context = ReplayContext(predictions, meta, days, opportunities.select(list(EPISODE_SCHEMA)))
    if (
        not context.matches.select("episode_id", "row_index")
        .sort("episode_id")
        .equals(opportunities.select("episode_id", "row_index").sort("episode_id"))
    ):
        raise ValueError("Forecast rows or event opportunities differ from frozen H09")
    record = json.loads((events_run / "metrics.json").read_text())[str(year)][task]
    stage = "validation" if part == "valid" else "test"
    baseline = record["policies"]["lightgbm"]["original_threshold"][stage]
    if (
        len(context.episodes) != baseline["onsets"]
        or len(context.available) != baseline["onsets_with_forecast_opportunity"]
    ):
        raise ValueError("Frozen event denominator differs")
    context.censored = baseline["left_censored_onsets_excluded"]
    return predictions, context
