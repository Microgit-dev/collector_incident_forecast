"""Regression checks for sampling, temporal separation and deployable thresholds."""

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from apps.forecasting import channel_model as M
from apps.forecasting.channel_model import _pr, _sample_rows, _split_dataset, pick_threshold, train
from apps.forecasting.domain import features as F


def _rows(days):
    return pl.DataFrame(
        {
            "channel_id": [1] * len(days),
            "day": days,
            "y": [False] * len(days),
            "y_orig": [False] * len(days),
            "fb": [False] * len(days),
            "fb_weight": [1.0] * len(days),
        }
    )


def test_sampling_is_reproducible_and_spread_across_time():
    days = [date(2020, 1, 1) + timedelta(days=i) for i in range(1000)]
    rows = _rows(days)
    sampled = _sample_rows(rows, 0.05)
    selected = sampled["day"].to_list()
    assert 25 < len(selected) < 80
    assert (max(selected) - min(selected)).days > 800  # old sampler kept one 50-day block
    assert sampled.equals(_sample_rows(rows, 0.05))
    assert set(selected) == set(_sample_rows(rows.reverse(), 0.05)["day"].to_list())
    assert sampled["weight"].unique().to_list() == [20.0]


def test_validation_and_test_keep_every_row_with_unit_weights():
    days = [date(2025, 1, 1) + timedelta(days=i) for i in range(500)]
    rows = _rows(days).with_columns(pl.lit(True).alias("fb"), pl.lit(3.0).alias("fb_weight"))
    sampled = _sample_rows(rows, 0.01)
    assert sampled.height == rows.height
    assert sampled["weight"].to_list() == [1.0] * len(days)
    assert sampled["weight_orig"].to_list() == [1.0] * len(days)


def test_training_always_retains_positive_and_feedback_rows():
    rows = _rows([date(2024, 1, 1) + timedelta(days=i) for i in range(4)]).with_columns(
        pl.Series("y", [True, False, False, False]),
        pl.Series("y_orig", [True, True, False, False]),
        pl.Series("fb", [False, True, True, False]),
        pl.Series("fb_weight", [1.0, 2.0, 3.0, 1.0]),
    )
    sampled = _sample_rows(rows, 1e-12)
    assert sampled.height == 3
    assert sampled["weight_orig"].to_list() == [1.0, 1.0, 1.0]
    assert sampled["weight"].to_list() == [1.0, 2.0, 3.0]


@pytest.mark.parametrize("rate", [0, -0.1, 1.1, float("nan")])
def test_invalid_sampling_rate_is_rejected(rate):
    with pytest.raises(ValueError, match="отрицательных"):
        _sample_rows(_rows([date(2024, 1, 1)]), rate)


@pytest.mark.parametrize("horizon", [1, 7])
def test_target_windows_do_not_cross_split_boundaries(horizon):
    days = [date(2024, 12, 20) + timedelta(days=i) for i in range(390)]
    parts = _split_dataset(_rows(days), horizon)
    assert parts["train"]["day"].max() == date(2025, 1, 1) - timedelta(days=horizon + 1)
    assert parts["valid"]["day"].min() == date(2025, 1, 1)
    assert parts["valid"]["day"].max() == date(2026, 1, 1) - timedelta(days=horizon + 1)
    assert parts["test"]["day"].min() == date(2026, 1, 1)
    assert sum(len(p) for p in parts.values()) == len(days) - 2 * horizon


def test_threshold_never_splits_tied_scores():
    p = np.full(100, 0.5)
    y = np.zeros(100, dtype=bool)
    y[np.argsort(-p)[:30]] = True
    assert pick_threshold(y, p, np.ones(100), 0.7) is None


def test_threshold_keeps_precision_at_full_stored_precision():
    p = np.r_[np.full(20, 0.50004), np.full(80, 0.50003)]
    y = np.r_[np.ones(20, dtype=bool), np.zeros(80, dtype=bool)]
    w = np.ones(100)
    threshold = pick_threshold(y, p, w, 0.7)
    assert threshold == 0.50004
    assert _pr(y, p >= threshold, w) == (1.0, 1.0)
    # Rounding to 4 decimals would add all 80 negatives at deployment.
    assert _pr(y, p >= round(threshold, 4), w)[0] == 0.2


def test_threshold_uses_weights_and_maximizes_recall_at_valid_group_boundaries():
    p = np.r_[np.full(20, 0.9), np.full(10, 0.8), np.full(10, 0.7)]
    y = np.r_[np.ones(30, dtype=bool), np.zeros(10, dtype=bool)]
    w = np.r_[np.ones(30), np.full(10, 10.0)]
    assert pick_threshold(y, p, w, 0.7) == 0.8


def test_threshold_empty_input_returns_none():
    assert pick_threshold(np.array([], dtype=bool), np.array([]), np.array([]), 0.7) is None


@pytest.mark.parametrize("horizon", [0, -24, 23, 25])
def test_non_daily_horizon_is_rejected_before_reading_data(horizon):
    with pytest.raises(ValueError, match="Горизонт"):
        train(horizon_hours=horizon)


def test_training_saves_correct_protocol_and_reloadable_model(monkeypatch, settings, tmp_path):
    """End-to-end training smoke check on a small artificial fixture, not a quality experiment."""
    import json

    settings.ARTIFACTS_DIR = tmp_path
    days = (
        [date(2024, 1, 1) + timedelta(days=i) for i in range(240)]
        + [date(2025, 1, 1) + timedelta(days=i) for i in range(100)]
        + [date(2026, 1, 1) + timedelta(days=i) for i in range(100)]
    )
    frame = _rows(days).with_columns(
        *[pl.lit(0.0).alias(f) for f in F.FEATURES if f not in [*F.CATEGORICAL, "faults_7"]],
        pl.lit("normal").cast(pl.Enum(F.STATES)).alias("last_state"),
        pl.lit("Датчик дыма").alias("sensor_type"),
        pl.Series("y", [i % 4 == 0 for i in range(len(days))]),
        pl.Series("faults_7", [float(i % 4 == 0) for i in range(len(days))]),
        pl.lit(None, dtype=pl.Datetime("us", "UTC")).alias("next_fault_ts"),
    )
    frame = _sample_rows(frame.with_columns(pl.col("y").alias("y_orig")), 1.0)
    monkeypatch.setattr(M, "build_dataset", lambda *args, **kwargs: (frame, {}, {}))
    monkeypatch.setattr(M, "PARAMS", M.PARAMS | {"min_data_in_leaf": 5, "num_threads": 1})
    result = train(neg_rate=1.0)
    assert result.metrics["rows"] == {"train": 240, "valid": 100, "test": 100}
    assert result.metrics["evaluation_protocol"]["validation_test"] == "full_population_unit_weights"
    assert result.train_period["train"] == [str(days[0]), str(days[239])]
    meta = json.loads(result.artifact.with_suffix(".json").read_text())
    assert meta["levels"] == result.metrics["levels"]
    booster, _ = M._load(str(result.artifact))
    x = M.to_matrix(frame, result.sensor_types, result.columns)
    assert np.isfinite(booster.predict(x)).all()
