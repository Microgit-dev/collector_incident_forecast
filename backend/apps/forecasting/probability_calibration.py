"""Calibration on data disjoint from model early stopping and calibrator selection."""

from datetime import date

import numpy as np
import polars as pl


def calibration_periods(valid):
    return {
        "early_stop": valid.filter(pl.col("day") < date(2025, 3, 31)),
        "fit_calibration": valid.filter(
            (pl.col("day") >= date(2025, 4, 1)) & (pl.col("day") < date(2025, 9, 30))
        ),
        "select_calibration": valid.filter(pl.col("day") >= date(2025, 10, 1)),
    }


def logits(p):
    clipped = np.clip(p, 1e-8, 1 - 1e-8)
    return np.log(clipped / (1 - clipped)).reshape(-1, 1)


def fit_calibrators(y, p):
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression

    sigmoid = LogisticRegression(C=1e6, max_iter=1000, random_state=42).fit(logits(p), y)
    isotonic = IsotonicRegression(out_of_bounds="clip", y_min=1e-8, y_max=1 - 1e-8).fit(p, y)
    return {"raw": None, "sigmoid": sigmoid, "isotonic": isotonic}


def calibrated_predict(name, calibrator, p):
    if name == "raw":
        return p
    if name == "sigmoid":
        return calibrator.predict_proba(logits(p))[:, 1]
    return calibrator.predict(p)


def reliability_bins(y, p, bins=10):
    """Quantile bins preserve visibility of rare-event probabilities; tied scores stay together."""
    edges = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    index = np.searchsorted(edges[1:-1], p, side="right")
    result = []
    for i in np.unique(index):
        mask = index == i
        result.append(
            {
                "count": int(mask.sum()),
                "mean_probability": float(p[mask].mean()),
                "observed_rate": float(y[mask].mean()),
            }
        )
    return result


def choose_calibration(metrics):
    return min(metrics, key=lambda name: (metrics[name]["brier"], metrics[name]["log_loss"]))
