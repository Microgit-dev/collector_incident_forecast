"""Shared provenance and evaluation for offline hypothesis experiments."""

import importlib.metadata
import json
import platform
import subprocess

import numpy as np

from . import channel_model as M
from .management.commands.benchmark_ml import budget_threshold


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


def start_run(output, source, hypothesis, **extra):
    output.mkdir(parents=True, exist_ok=False)
    config = {
        "hypothesis": hypothesis,
        "snapshot": str(source.folder),
        "snapshot_fingerprint": source.cache_key,
        "test_status": "diagnostic_2026_previously_used_in_development",
        "weather": "omitted",
        "python": platform.python_version(),
        "versions": {
            p: importlib.metadata.version(p) for p in ["numpy", "polars", "scikit-learn", "lightgbm"]
        },
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree": subprocess.check_output(["git", "status", "--porcelain"], text=True),
        **extra,
    }
    write_json(output / "config.json", config)
    (output / "working_tree.patch").write_bytes(subprocess.check_output(["git", "diff", "HEAD"]))
    return config


def evaluate_predictions(parts, predictions, budgets=(5, 20, 50)):
    """Fix each operating point on validation before examining diagnostic outcomes."""
    from sklearn.metrics import brier_score_loss, log_loss

    report = {}
    for model in predictions["valid"]:
        pv = predictions["valid"][model]
        records = {}
        for budget in budgets:
            threshold = budget_threshold(pv, budget * parts["valid"]["day"].n_unique())
            record = {"threshold_from_validation": threshold}
            for part in ("valid", "test"):
                frame, p = parts[part], predictions[part][model]
                y = frame["y"].to_numpy()
                metrics = M.evaluate(y, p, np.ones(len(y)), threshold, frame)
                metrics["false_alerts_per_day"] = round(
                    float(((p >= threshold) & ~y).sum()) / frame["day"].n_unique(), 3
                )
                metrics["brier"] = float(brier_score_loss(y, p))
                metrics["log_loss"] = float(log_loss(y, p, labels=[False, True]))
                record[part] = metrics
            records[str(budget)] = record
        report[model] = records
    return report


def reference_predictions(folder, task, parts, models=("rule", "constant", "logistic", "lightgbm")):
    import polars as pl

    predictions = {}
    for part in ("valid", "test"):
        reference = pl.read_parquet(folder / f"{task}_{part}_predictions.parquet")
        if not reference.select("channel_id", "day", "y").equals(
            parts[part].select("channel_id", "day", "y")
        ):
            raise ValueError(f"{task}/{part}: reference rows/labels do not match the current snapshot")
        predictions[part] = {model: reference[model].to_numpy() for model in models}
    return predictions
