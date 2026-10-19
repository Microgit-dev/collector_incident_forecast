from datetime import date

import numpy as np
import polars as pl

from apps.forecasting.probability_calibration import (
    calibrated_predict,
    calibration_periods,
    choose_calibration,
    fit_calibrators,
    reliability_bins,
)


def test_calibration_periods_are_disjoint_and_purge_one_day_targets():
    days = [
        date(2025, 1, 1),
        date(2025, 3, 30),
        date(2025, 3, 31),
        date(2025, 4, 1),
        date(2025, 9, 29),
        date(2025, 9, 30),
        date(2025, 10, 1),
        date(2025, 12, 30),
    ]
    parts = calibration_periods(pl.DataFrame({"day": days}))
    assert parts["early_stop"]["day"].to_list() == days[:2]
    assert parts["fit_calibration"]["day"].to_list() == [days[3], days[4]]
    assert parts["select_calibration"]["day"].to_list() == days[6:]


def test_calibration_choice_uses_probability_error_not_test_or_ranking():
    metrics = {
        "raw": {"brier": 0.03, "log_loss": 0.2, "test_brier": 0.001},
        "sigmoid": {"brier": 0.02, "log_loss": 0.1, "test_brier": 0.9},
    }
    assert choose_calibration(metrics) == "sigmoid"


def test_calibrators_return_finite_probabilities_and_monotone_order():
    p = np.linspace(0.001, 0.9, 200)
    y = np.arange(200) > 120
    calibrators = fit_calibrators(y, p)
    for name, calibrator in calibrators.items():
        result = calibrated_predict(name, calibrator, p)
        assert np.isfinite(result).all()
        assert ((result >= 0) & (result <= 1)).all()
        assert (np.diff(result) >= 0).all()


def test_reliability_keeps_ties_and_all_observations():
    y = np.array([True, False, False, False])
    p = np.full(4, 0.1)
    assert reliability_bins(y, p) == [{"count": 4, "mean_probability": 0.1, "observed_rate": 0.25}]
