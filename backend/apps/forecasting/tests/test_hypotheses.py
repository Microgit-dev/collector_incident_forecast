import numpy as np
import polars as pl
import pytest

from apps.forecasting.management.commands.benchmark_catboost import cat_frame, choose_trial, validation_trial


def test_catboost_trial_selection_uses_validation_only():
    trials = [
        {"depth": 4, "validation_recall_at_20": 0.2, "validation_ap": 0.15, "test_ap": 0.9},
        {"depth": 6, "validation_recall_at_20": 0.3, "validation_ap": 0.14, "test_ap": 0.1},
    ]
    assert choose_trial(trials)["depth"] == 6


def test_external_ap_for_constant_score_matches_event_prevalence():
    y = np.r_[np.ones(2, dtype=bool), np.zeros(98, dtype=bool)]
    result = validation_trial(y, np.full(100, 0.1), days=1, depth=4, trees=50)
    assert result["validation_ap"] == pytest.approx(0.02)
    assert result["validation_recall_at_20"] == 0  # a tied group of 100 cannot fit a budget of 20


def test_catboost_pool_handles_missing_numeric_and_unseen_category(tmp_path):
    catboost = pytest.importorskip("catboost")
    frame = pl.DataFrame(
        {
            "faults_7": [0.0, None, 1.0, 2.0] * 10,
            "last_state": ["normal"] * 40,
            "sensor_type": ["gas", "smoke"] * 20,
        }
    )
    columns = ["faults_7", "last_state", "sensor_type"]
    model = catboost.CatBoostClassifier(
        iterations=2, depth=2, verbose=False, thread_count=1, allow_writing_files=False
    )
    train = catboost.Pool(
        cat_frame(frame, columns), np.array([0, 0, 1, 1] * 10), cat_features=["last_state", "sensor_type"]
    )
    model.fit(train)
    unseen = frame.head(2).with_columns(pl.lit("new_kind").alias("sensor_type"))
    result = model.predict_proba(
        catboost.Pool(cat_frame(unseen, columns), cat_features=["last_state", "sensor_type"])
    )
    path = tmp_path / "model.cbm"
    model.save_model(path)
    restored = catboost.CatBoostClassifier().load_model(path)
    assert np.isfinite(result).all() and restored.tree_count_ == 2
