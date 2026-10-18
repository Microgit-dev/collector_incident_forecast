from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl

from apps.forecasting.node_replay import NodeReplayContext, aggregate_node_scores, cluster_node_onsets


def channels():
    return pl.DataFrame({"channel_id": [1, 2, 3], "node_id": [10, 10, 20]})


def episodes():
    base = datetime(2024, 1, 2, 5, tzinfo=UTC)
    return pl.DataFrame(
        {
            "channel_id": [1, 2, 3, 1],
            "node_id": [10, 10, 20, 10],
            "start_at": [base, base + timedelta(minutes=15), base, base + timedelta(hours=2)],
            "left_censored": [False] * 4,
        }
    )


def test_node_clusters_group_different_channels_without_mixing_nodes():
    clusters = cluster_node_onsets(episodes(), "gas")
    assert len(clusters) == 3
    assert clusters.filter(pl.col("node_id") == 10)["channel_onsets"].to_list() == [2, 1]
    assert clusters.filter(pl.col("node_id") == 20)["channel_onsets"].to_list() == [1]


def test_node_cluster_gap_keeps_seconds_and_ids_include_the_task():
    base = episodes().head(1)
    after = base.with_columns((pl.col("start_at") + timedelta(minutes=30, seconds=1)).alias("start_at"))
    both = pl.concat([base, after])
    gas = cluster_node_onsets(both, "gas")
    assert len(gas) == 2  # total_minutes() truncation would incorrectly merge these points
    flood = cluster_node_onsets(both, "flood")
    assert set(gas["episode_id"].to_list()).isdisjoint(flood["episode_id"].to_list())


def test_node_aggregation_ignores_labels_and_uses_only_current_channel_scores():
    frame = pl.DataFrame(
        {
            "channel_id": [1, 2, 3],
            "day": [date(2024, 1, 1)] * 3,
            "y": [True, False, True],
            "m": [0.2, 0.8, 0.4],
        }
    )
    result = aggregate_node_scores(frame, channels(), ["m"])
    assert result.equals(aggregate_node_scores(frame.with_columns(~pl.col("y")), channels(), ["m"]))
    assert result["m_max"].to_list() == [0.8, 0.4]
    np.testing.assert_allclose(result["m_mean"].to_numpy(), [0.5, 0.4])
    np.testing.assert_allclose(result["m_top3"].to_numpy(), [0.5, 0.4])
    future = frame.with_columns(pl.lit(date(2024, 1, 2)).alias("day"), pl.lit(0.99).alias("m"))
    all_rows = aggregate_node_scores(pl.concat([frame, future]), channels(), ["m"])
    assert result.equals(all_rows.filter(pl.col("day") == date(2024, 1, 1)))


def test_node_matching_credits_node_events_and_exports_unambiguous_units():
    frame = pl.DataFrame({"channel_id": [1, 2, 3], "day": [date(2024, 1, 1)] * 3, "m": [0.2, 0.8, 0.4]})
    scores = aggregate_node_scores(frame, channels(), ["m"])
    context = NodeReplayContext(scores, cluster_node_onsets(episodes(), "gas"))
    selected = np.array([0])
    metrics = context.evaluate(selected)
    assert metrics["onsets"] == 3 and metrics["detected_onsets"] == 2
    assert metrics["onset_recall"] == 2 / 3
    assert metrics["sample_unit"] == "node_day"
    assert metrics["positive_node_days"] == 2
    assert "journal_event_precision" not in metrics
    cards = context.alert_rows(selected, scores["m_max"].to_numpy())
    assert cards["node_id"].to_list() == [10]
    assert "channel_id" not in cards.columns
    assert cards["forecast_unit"].to_list() == ["node"]
