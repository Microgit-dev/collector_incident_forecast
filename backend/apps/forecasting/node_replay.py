"""H09c: separate node-level forecasting units, event clusters and aggregation heads."""

import hashlib
from datetime import timedelta

import polars as pl

from .event_replay import ReplayContext


def cluster_node_onsets(episodes, task, gap_minutes=30):
    """Cluster known channel onsets by node and consecutive time gap, not physical-incident truth."""
    if gap_minutes < 0:
        raise ValueError("Nonnegative node episode gap required")
    known = episodes.filter(~pl.col("left_censored")).sort("node_id", "start_at", "channel_id")
    grouped = (
        known.with_columns(
            (
                (pl.col("start_at") - pl.col("start_at").shift(1).over("node_id"))
                > timedelta(minutes=gap_minutes)
            )
            .fill_null(True)
            .cast(pl.UInt32)
            .alias("_new")
        )
        .with_columns(pl.col("_new").cum_sum().over("node_id").alias("_cluster"))
        .group_by("node_id", "_cluster")
        .agg(
            pl.col("start_at").min(),
            pl.col("start_at").max().alias("last_onset_at"),
            pl.col("channel_id").unique().sort().alias("source_channels"),
            pl.len().cast(pl.Int64).alias("channel_onsets"),
        )
        .sort("node_id", "start_at")
    )
    identifiers = [
        hashlib.sha256(f"{task}:node:{node}:{ts.isoformat()}".encode()).hexdigest()[:24]
        for node, ts in grouped.select("node_id", "start_at").iter_rows()
    ]
    return grouped.with_columns(pl.Series("episode_id", identifiers, dtype=pl.String)).drop("_cluster")


def aggregate_node_scores(predictions, meta, models):
    """Label-blind node heads. These are ranking scores, not calibrated node probabilities."""
    if predictions.select("channel_id", "day").is_duplicated().any():
        raise ValueError("Duplicate channel forecasts")
    frame = predictions.select("channel_id", "day", *models).join(
        meta.select("channel_id", "node_id"), on="channel_id", how="left", validate="m:1"
    )
    if frame["node_id"].null_count():
        raise ValueError("Unknown forecast node")
    aggregations = []
    for model in models:
        aggregations.extend(
            [
                pl.col(model).max().alias(f"{model}_max"),
                pl.col(model).mean().alias(f"{model}_mean"),
                pl.col(model).top_k(3).mean().alias(f"{model}_top3"),
            ]
        )
    return (
        frame.group_by("node_id", "day")
        .agg(
            pl.col("channel_id").sort().alias("source_channels"),
            pl.len().alias("eligible_channels"),
            *aggregations,
        )
        .with_columns(
            pl.lit(0.5).alias("constant"),
            (pl.col("eligible_channels") / (pl.col("eligible_channels") + 1.0)).alias("channel_count"),
        )
        .sort("node_id", "day")
    )


class NodeReplayContext(ReplayContext):
    """Adapt the shared matching engine internally; exported cards retain explicit node units."""

    def __init__(self, node_scores, clusters):
        keys = clusters.with_columns(
            pl.col("start_at").dt.convert_time_zone("Europe/Moscow").dt.date().alias("target_day")
        )
        facts = keys.group_by("node_id", "target_day").agg(pl.len().alias("event_rows"))
        predictions = (
            node_scores.with_columns((pl.col("day") + timedelta(days=1)).alias("target_day"))
            .join(facts, on=["node_id", "target_day"], how="left", validate="m:1", maintain_order="left")
            .with_columns((pl.col("event_rows").fill_null(0) > 0).alias("y"))
            .drop("event_rows", "target_day")
        )
        # channel_id is only the generic matching engine's internal entity key in this adapter.
        predictions = predictions.rename({"node_id": "channel_id"})
        ids = node_scores["node_id"].unique()
        meta = pl.DataFrame({"channel_id": ids, "node_id": ids, "sensor_type": ["node"] * len(ids)})
        events = clusters.select(
            "episode_id",
            pl.col("node_id").alias("channel_id"),
            "node_id",
            "start_at",
            pl.col("last_onset_at").alias("end_bound"),
            pl.col("last_onset_at").alias("last_at"),
            pl.lit(False).alias("left_censored"),
            pl.lit(False).alias("right_censored"),
        )
        days = facts.rename({"node_id": "channel_id", "target_day": "day"})
        super().__init__(predictions, meta, days, events)

    def evaluate(self, selected):
        return super().evaluate(selected) | {
            "sample_unit": "node_day",
            "event_unit": "node_onset_cluster",
            "alert_unit": "node_task_day",
        }

    def alert_rows(self, selected, scores):
        return (
            super()
            .alert_rows(selected, scores)
            .drop("channel_id", "sensor_type")
            .with_columns(pl.lit("node").alias("forecast_unit"))
        )


def choose_node_trial(trials):
    return max(
        trials,
        key=lambda r: (
            r["validation"]["onset_recall"],
            r["validation"]["onset_alert_precision"],
            -r["validation"]["alerts"],
        ),
    )
