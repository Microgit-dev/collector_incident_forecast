"""H01: compare simple baselines and the corrected LightGBM on identical temporal splits."""

import importlib.metadata
import json
import platform
import subprocess
import time
from pathlib import Path

import joblib
import numpy as np
import polars as pl
from django.core.management.base import BaseCommand

from apps.forecasting import channel_model as M
from apps.forecasting import specs
from apps.forecasting.domain import features as F
from apps.forecasting.offline import ParquetHistory


def budget_threshold(scores, max_alerts):
    """Largest whole score group fitting the validation budget; never split ties by row order."""
    values, counts = np.unique(scores, return_counts=True)
    values, counts = values[::-1], counts[::-1]
    eligible = np.flatnonzero(np.cumsum(counts) <= max_alerts)
    return float(values[eligible[-1]]) if len(eligible) else float(np.nextafter(values[0], np.inf))


def predict_batches(model, x, batch=100_000):
    return np.concatenate([model.predict_proba(x[i : i + batch])[:, 1] for i in range(0, len(x), batch)])


class Command(BaseCommand):
    help = "Run H01 rules/constant/logistic/LightGBM baselines against an offline snapshot"

    def add_arguments(self, parser):
        parser.add_argument("--snapshot", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--tasks", nargs="+", choices=list(specs.SPECS), default=list(specs.SPECS))
        parser.add_argument("--budgets", nargs="+", type=int, default=[5, 20, 50])

    def handle(self, *args, snapshot, output, tasks, budgets, **options):
        from sklearn.compose import ColumnTransformer
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler

        source = ParquetHistory(snapshot)
        output.mkdir(parents=True, exist_ok=False)
        config = {
            "hypothesis": "H01: predictive value beyond simple rules and base rate",
            "snapshot": str(source.folder),
            "snapshot_fingerprint": source.cache_key,
            "tasks": tasks,
            "horizon_hours": 24,
            "budgets_alerts_per_day_all_channels": budgets,
            "weather": "omitted_in_all_candidates",
            "test_status": "diagnostic_2026_already_used_in_prior_development",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "versions": {
                p: importlib.metadata.version(p) for p in ["polars", "numpy", "scikit-learn", "lightgbm"]
            },
            "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "working_tree": subprocess.check_output(["git", "status", "--porcelain"], text=True),
        }
        (output / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2))
        (output / "working_tree.patch").write_bytes(subprocess.check_output(["git", "diff", "HEAD"]))
        report = {}
        for task in tasks:
            spec = specs.get(task)
            started = time.monotonic()

            def progress(fraction, stage, task=task):
                self.stdout.write(f"[{task}] {fraction:5.0%} {stage}")
                self.stdout.flush()

            result = M.train(spec, progress=progress, source=source)
            dataset, _, _ = M.build_dataset(spec, source=source)
            parts = M._split_dataset(dataset, 1)
            del dataset
            types, columns = result.sensor_types, result.columns
            x_train = M.to_matrix(parts["train"], types, columns)
            y_train, weights = parts["train"]["y"].to_numpy(), parts["train"]["weight"].to_numpy()
            cat = [columns.index(c) for c in F.CATEGORICAL]
            numeric = [i for i in range(len(columns)) if i not in cat]
            logistic = Pipeline(
                [
                    (
                        "features",
                        ColumnTransformer(
                            [
                                (
                                    "numeric",
                                    Pipeline(
                                        [
                                            ("impute", SimpleImputer(keep_empty_features=True)),
                                            ("scale", StandardScaler()),
                                        ]
                                    ),
                                    numeric,
                                ),
                                ("category", OneHotEncoder(handle_unknown="ignore"), cat),
                            ]
                        ),
                    ),
                    ("classifier", LogisticRegression(max_iter=500, tol=1e-4, random_state=42)),
                ]
            )
            progress(0.0, "Logistic regression")
            fit_started = time.monotonic()
            logistic.fit(x_train, y_train, classifier__sample_weight=weights)
            logistic_seconds = time.monotonic() - fit_started
            joblib.dump(logistic, output / f"{task}_logistic.joblib")
            prior = float(np.average(y_train, weights=weights))
            del x_train, y_train, weights
            booster, _ = M._load(str(result.artifact))
            predictions = {}
            for part in ["valid", "test"]:
                x = M.to_matrix(parts[part], types, columns)
                predictions[part] = {
                    "rule": spec.baseline(parts[part]).astype(float),
                    "constant": np.full(len(x), prior),
                    "logistic": predict_batches(logistic, x),
                    "lightgbm": booster.predict(x),
                }
                parts[part].select("channel_id", "day", "y").with_columns(
                    *[pl.Series(name, p) for name, p in predictions[part].items()]
                ).write_parquet(output / f"{task}_{part}_predictions.parquet")
                del x
            task_report = {
                "rows": result.metrics["rows"],
                "protocol": result.metrics["evaluation_protocol"],
                "lightgbm_artifact": str(result.artifact),
                "logistic_fit_seconds": logistic_seconds,
                "models": {},
            }
            for name in ["rule", "constant", "logistic", "lightgbm"]:
                pv, pt = predictions["valid"][name], predictions["test"][name]
                model_report = {}
                for budget in budgets:
                    threshold = budget_threshold(pv, budget * parts["valid"]["day"].n_unique())
                    scores = {}
                    for part, pred in [("valid", pv), ("test", pt)]:
                        frame = parts[part]
                        metrics = M.evaluate(
                            frame["y"].to_numpy(), pred, np.ones(frame.height), threshold, frame
                        )
                        actual = (pred >= threshold) & ~frame["y"].to_numpy()
                        metrics["false_alerts_per_day"] = round(
                            float(actual.sum()) / frame["day"].n_unique(), 2
                        )
                        scores[part] = metrics
                    model_report[str(budget)] = {"threshold_from_validation": threshold, **scores}
                task_report["models"][name] = model_report
            # Include the engineering rule at its natural operating point as well.
            task_report["natural_rule_test"] = M.evaluate(
                parts["test"]["y"].to_numpy(),
                predictions["test"]["rule"],
                np.ones(parts["test"].height),
                0.5,
                parts["test"],
            )
            task_report["seconds"] = round(time.monotonic() - started, 2)
            report[task] = task_report
            (output / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            self.stdout.write(f"[{task}] COMPLETE {task_report['seconds']} s")
            del parts, predictions, logistic
        self.stdout.write(self.style.SUCCESS(f"H01 results: {output}"))
