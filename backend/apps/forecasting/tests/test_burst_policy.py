from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from apps.forecasting.burst_policy import BudgetPolicy, BudgetStream, choose_budget_trial
from apps.forecasting.event_replay import AlertPolicy


def frame(channels=10, days=10):
    return pl.DataFrame(
        {
            "channel_id": list(range(1, channels + 1)) * days,
            "node_id": [1] * channels * days,
            "day": [date(2024, 1, 1) + timedelta(days=d) for d in range(days) for _ in range(channels)],
        }
    )


def test_hash_ties_fill_budget_without_outcomes_and_are_order_independent():
    rows = frame(100, 1)
    policy = BudgetPolicy("hash", 0.1)
    selected = BudgetStream(rows, np.full(len(rows), 0.5)).run_budget(policy)[0]
    assert len(selected) == 20
    reverse = rows.reverse()
    again = BudgetStream(reverse, np.full(len(rows), 0.5)).run_budget(policy)[0]
    assert rows[selected].equals(reverse[again])
    other = BudgetStream(rows, np.full(len(rows), 0.5)).run_budget(BudgetPolicy("hash", 0.1, seed=43))[0]
    assert set(selected) != set(other)


def test_weekly_reserve_uses_past_only_and_checks_every_rolling_window():
    rows = frame(10, 20)
    policy = BudgetPolicy("weekly", 0.1, daily_budget=2, window_days=7)
    stream = BudgetStream(rows, np.full(len(rows), 0.5))
    selected, _, diagnostics = stream.run_budget(policy)
    emitted = rows[selected].group_by("day").len().sort("day")
    counts = np.zeros(20, dtype=int)
    for d, n in emitted.iter_rows():
        counts[(d - date(2024, 1, 1)).days] = n
    assert counts[:3].tolist() == [10, 4, 0]
    assert max(np.convolve(counts, np.ones(7, dtype=int), mode="valid")) <= 14
    assert diagnostics["max_alerts_in_rolling_window"] <= 14
    prefix = BudgetStream(rows.head(20), np.full(20, 0.5)).run_budget(policy)[0]
    assert selected[selected < 20].tolist() == prefix.tolist()


def test_budget_state_carries_over_and_spending_cannot_come_from_future():
    rows = frame(10, 10)
    policy = BudgetPolicy("weekly", 0.1, daily_budget=2, window_days=7)
    _, state, _ = BudgetStream(rows.head(20), np.full(20, 0.5)).run_budget(policy)
    selected, _, _ = BudgetStream(rows.slice(20, 30), np.full(30, 0.5)).run_budget(policy, state)
    assert len(selected) == 0
    with pytest.raises(ValueError, match="precede"):
        BudgetStream(rows, np.full(len(rows), 0.5)).run_budget(policy, state)


def test_group_mode_matches_existing_daily_policy_and_burst_limit_is_respected():
    rows = frame(10, 10)
    scores = np.tile(np.linspace(0.9, 0.1, 10), 10)
    stream = BudgetStream(rows, scores)
    old = stream.run(AlertPolicy("daily", 0.0, 3))[0]
    new = stream.run_budget(BudgetPolicy("daily", 0.0, 3, split_ties=False))[0]
    assert old.tolist() == new.tolist()
    chosen = stream.run_budget(BudgetPolicy("weekly", 0.1, 2, 7, burst_limit=6))[0]
    assert rows[chosen].group_by("day").len()["len"].max() <= 6


def test_policy_selection_never_picks_sensitivity_seed_or_other_budget_family():
    def trial(seed, window, recall):
        return {
            "policy": {"seed": seed, "window_days": window},
            "validation": {"onset_recall": recall, "onset_alert_precision": 0.1, "alerts": 20},
        }

    trials = [trial(42, 1, 0.2), trial(43, 1, 0.9), trial(42, 7, 0.8)]
    assert choose_budget_trial(trials, 1)["validation"]["onset_recall"] == 0.2


def test_reusing_opportunities_detects_a_changed_forecast_reference(tmp_path):
    import json
    from datetime import UTC, datetime

    from apps.forecasting.event_history import compress_observations, episodes_from_runs
    from apps.forecasting.event_replay import ReplayContext
    from apps.forecasting.replay_io import load_frozen_replay

    from .test_event_replay import END, META, raw_flags

    reference, events = tmp_path / "reference", tmp_path / "events"
    (reference / "2024").mkdir(parents=True)
    (events / "2024").mkdir(parents=True)
    raw = raw_flags([datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC)], [False, True])
    one = episodes_from_runs(compress_observations(raw.lazy(), 0).collect(), META, {0: END}, "gas")
    episodes = pl.concat(
        [
            one,
            one.with_columns(pl.lit(2).cast(pl.Int64).alias("channel_id"), pl.lit("two").alias("episode_id")),
        ]
    )
    preds = pl.DataFrame(
        {"channel_id": [1, 2], "day": [date(2024, 1, 1)] * 2, "y": [True, True], "lightgbm": [0.9, 0.8]}
    )
    facts = pl.DataFrame({"channel_id": [1, 2], "day": [date(2024, 1, 2)] * 2, "event_rows": [1, 1]})
    context = ReplayContext(preds, META, facts, episodes)
    preds.write_parquet(reference / "2024/gas_valid_predictions.parquet")
    facts.write_parquet(events / "gas_event_days.parquet")
    context.matches.write_parquet(events / "2024/gas_valid_episode_opportunities.parquet")
    (events / "metrics.json").write_text(
        json.dumps(
            {
                "2024": {
                    "gas": {
                        "policies": {
                            "lightgbm": {
                                "original_threshold": {"validation": context.evaluate(np.array([0]))}
                            }
                        }
                    }
                }
            }
        )
    )
    _, restored = load_frozen_replay(reference, events, 2024, "gas", "valid", META)
    assert len(restored.available) == 2
    preds.reverse().write_parquet(reference / "2024/gas_valid_predictions.parquet")
    with pytest.raises(ValueError, match="differ from frozen"):
        load_frozen_replay(reference, events, 2024, "gas", "valid", META)
