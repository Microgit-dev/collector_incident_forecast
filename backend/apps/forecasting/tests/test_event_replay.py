from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from apps.forecasting.event_history import compress_observations, episodes_from_runs, observations
from apps.forecasting.event_replay import (
    AlertPolicy,
    AlertStream,
    ReplayContext,
    choose_policy,
    forecast_period_end,
)

META = pl.DataFrame({"channel_id": [1, 2], "node_id": [10, 10], "sensor_type": ["gas", "gas"]})
END = datetime(2025, 1, 1, tzinfo=UTC)


def raw_flags(times, flags, facets=None):
    return pl.DataFrame(
        {
            "channel_id": [1] * len(times),
            "facet": facets or ["primary"] * len(times),
            "ts": times,
            "event": flags,
        }
    )


def test_gas_state_ignores_sentinel_numeric_and_accepts_drift():
    raw = pl.DataFrame(
        {
            "channel_id": [1] * 4,
            "facet": ["primary"] * 4,
            "ts": [datetime(2024, 1, 1, i, tzinfo=UTC) for i in range(4)],
            "quality": ["ok", "sentinel", "drift", "ok"],
            "numeric": [1.0, 9999.0, -0.02, None],
        }
    )
    obs = observations(raw.lazy(), "gas").collect()
    assert obs["event"].to_list() == [True, False]


def test_repeated_state_across_new_year_does_not_create_a_second_onset():
    before = raw_flags(
        [datetime(2023, 12, 30, tzinfo=UTC), datetime(2023, 12, 31, tzinfo=UTC)], [False, True]
    )
    after = raw_flags([datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC)], [True, False])
    runs = pl.concat([compress_observations(x.lazy(), 0).collect() for x in [before, after]])
    episodes = episodes_from_runs(runs, META, {0: END}, "gas")
    assert len(episodes) == 1
    assert episodes["start_at"][0] == datetime(2023, 12, 31, tzinfo=UTC)
    assert not episodes["left_censored"][0]
    assert episodes["end_bound"][0] == datetime(2024, 1, 2, tzinfo=UTC)
    reset = runs.with_columns(
        pl.when(pl.col("start_at").dt.year() == 2024).then(1).otherwise(0).cast(pl.Int32).alias("segment")
    )
    reset_episodes = episodes_from_runs(reset, META, {0: datetime(2024, 1, 1, tzinfo=UTC), 1: END}, "gas")
    assert len(reset_episodes) == 2
    assert reset_episodes["left_censored"].to_list() == [False, True]


def test_aspects_remain_independent_and_short_recoveries_merge():
    base = datetime(2024, 1, 1, 9, tzinfo=UTC)
    times = [base + timedelta(minutes=m) for m in [0, 60, 65, 80, 90, 121, 130]]
    frame = raw_flags(times, [False, True, False, True, False, True, False])
    episodes = episodes_from_runs(
        compress_observations(frame.lazy(), 0).collect(), META, {0: END}, "sensor_failure"
    )
    assert len(episodes) == 2
    assert episodes["start_at"].to_list() == [times[1], times[5]]
    extra = raw_flags([base + timedelta(minutes=m) for m in [61, 62]], [False, False], ["power", "power"])
    revised = episodes_from_runs(
        compress_observations(pl.concat([frame, extra]).lazy(), 0).collect(), META, {0: END}, "sensor_failure"
    )
    assert episodes.equals(revised)


def test_simultaneous_conflicting_observations_keep_event_without_order_dependence():
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    raw = raw_flags([ts, ts, ts + timedelta(hours=1)], [True, False, True])
    a = compress_observations(raw.lazy(), 0).collect()
    b = compress_observations(raw.reverse().lazy(), 0).collect()
    assert a.equals(b)
    assert a["event"].to_list() == [True]
    assert episodes_from_runs(a, META, {0: END}, "gas")["left_censored"].to_list() == [True]


def test_episode_definition_for_validation_cannot_use_later_facets_or_recoveries():
    base = datetime(2024, 1, 1, tzinfo=UTC)
    prefix = raw_flags([base, base + timedelta(hours=1)], [False, True])
    future = raw_flags([base + timedelta(days=2)], [True], ["power"])
    cutoff = base + timedelta(days=1)
    full = compress_observations(pl.concat([prefix, future]).lazy(), 0).collect()
    before = compress_observations(prefix.lazy(), 0).collect()
    a = episodes_from_runs(full, META, {0: END}, "sensor_failure", cutoff=cutoff)
    b = episodes_from_runs(before, META, {0: END}, "sensor_failure", cutoff=cutoff)
    assert a.equals(b)
    assert not a["left_censored"][0]


def forecast_rows(days=4):
    return pl.DataFrame(
        {
            "channel_id": [1, 2] * days,
            "node_id": [10, 10] * days,
            "day": [date(2024, 1, d) for d in range(1, days + 1) for _ in range(2)],
        }
    )


def test_budget_keeps_whole_ties_and_node_collapse_is_deterministic():
    frame = forecast_rows(1)
    stream = AlertStream(frame, [0.9, 0.9])
    assert len(stream.run(AlertPolicy("cap", 0.0, 1))[0]) == 0
    selected = stream.run(AlertPolicy("node", 0.0, 1, one_per_node=True))[0]
    assert frame[selected]["channel_id"].to_list() == [1]
    rev = AlertStream(frame.reverse(), [0.9, 0.9])
    assert frame.reverse()[rev.run(AlertPolicy("node", 0.0, 1, one_per_node=True))[0]][
        "channel_id"
    ].to_list() == [1]


def test_cooldown_updates_only_after_emission_and_allows_exact_boundary():
    frame = forecast_rows()
    selected, _, _ = AlertStream(frame, [0.9, 0.8] * 4).run(AlertPolicy("cd", 0.0, 1, 48))
    assert selected.tolist() == [0, 3, 4, 7]  # first rejected channel can be picked next day
    solo = frame.filter(pl.col("channel_id") == 1)
    selected, _, _ = AlertStream(solo, [0.9] * 4).run(AlertPolicy("cd", 0.0, 1, 48))
    assert selected.tolist() == [0, 2]


def test_cooldown_state_carries_across_period_and_rejects_future_state():
    frame = forecast_rows(4).filter(pl.col("channel_id") == 1)
    policy = AlertPolicy("cd", 0.0, 1, 72)
    _, state, _ = AlertStream(frame.head(2), [0.9] * 2).run(policy)
    chosen, _, _ = AlertStream(frame.tail(2), [0.9] * 2).run(policy, state)
    assert chosen.tolist() == [1]
    with pytest.raises(ValueError, match="precede"):
        AlertStream(frame, [0.9] * 4).run(policy, state)


def test_future_predictions_and_outcomes_cannot_change_past_policy():
    frame = forecast_rows(2).with_columns(pl.lit(False).alias("y"))
    policy = AlertPolicy("cd", 0.0, 1, 48)
    old = AlertStream(frame, [0.9, 0.8] * 2).run(policy)[0]
    future = forecast_rows(3).tail(2).with_columns(pl.lit(True).alias("y"))
    joined = pl.concat([frame.with_columns(pl.lit(True).alias("y")), future])
    new = AlertStream(joined, [0.9, 0.8] * 2 + [0.999, 0.998]).run(policy)[0]
    assert new[new < len(frame)].tolist() == old.tolist()


def test_replay_counts_unforecastable_onsets_and_exact_midnight_lead():
    raw = raw_flags(
        [datetime(2024, 1, 1, 12, tzinfo=UTC), datetime(2024, 1, 1, 21, tzinfo=UTC)], [False, True]
    )
    episodes = episodes_from_runs(compress_observations(raw.lazy(), 0).collect(), META, {0: END}, "gas")
    other = episodes.with_columns(
        pl.lit(2).cast(pl.Int64).alias("channel_id"), pl.lit("second").alias("episode_id")
    )
    future = episodes.with_columns(
        pl.lit(datetime(2024, 1, 2, 21, tzinfo=UTC)).alias("start_at"), pl.lit("future").alias("episode_id")
    )
    frame = pl.DataFrame({"channel_id": [1], "day": [date(2024, 1, 1)], "y": [True]})
    facts = pl.DataFrame({"channel_id": [1], "day": [date(2024, 1, 2)], "event_rows": [1]})
    context = ReplayContext(frame, META, facts, pl.concat([episodes, other, future]))
    metric = context.evaluate(np.array([0]))
    assert metric["onsets"] == 2
    assert metric["onsets_without_forecast_opportunity"] == 1
    assert metric["onset_recall"] == 0.5
    assert metric["forecastable_onset_recall"] == 1.0
    assert metric["lead_hours"]["median"] == 0.0
    assert metric["onset_recall_min_lead"]["1"] == 0.0
    with pytest.raises(ValueError, match="labels disagree"):
        ReplayContext(frame.with_columns(pl.lit(False).alias("y")), META, facts, episodes)


def test_selection_uses_validation_and_excludes_unbounded_comparator():
    def trial(name, recall, test, limit=20):
        return {
            "policy": asdict(AlertPolicy(name, 0.1, limit)),
            "validation": {"onset_recall": recall, "onset_alert_precision": 0.1, "alerts": 20},
            "test": {"onset_recall": test},
        }

    assert (
        choose_policy([trial("a", 0.5, 0.1), trial("b", 0.4, 0.9), trial("raw", 1.0, 1.0, None)])["policy"][
            "name"
        ]
        == "a"
    )


def test_period_cutoff_is_utc_end_of_outcome_not_feature_day():
    predictions = pl.DataFrame({"day": [date(2023, 6, 29)]})
    cutoff = forecast_period_end(predictions)
    assert cutoff == datetime(2023, 6, 30, 21, tzinfo=UTC)
    raw = raw_flags([datetime(2023, 6, 29, tzinfo=UTC), datetime(2023, 6, 30, tzinfo=UTC)], [False, True])
    episodes = episodes_from_runs(
        compress_observations(raw.lazy(), 0).collect(), META, {0: END}, "gas", cutoff=cutoff
    )
    assert len(episodes) == 1
    assert episodes["end_bound"][0] == cutoff
