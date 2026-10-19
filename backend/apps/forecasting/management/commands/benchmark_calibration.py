"""H08: fit/selection split for calibrating a newly frozen early-stop-only base model."""

import time
from pathlib import Path

import joblib
import numpy as np
import polars as pl
from django.core.management.base import BaseCommand
from sklearn.metrics import brier_score_loss, log_loss

from apps.forecasting import channel_model as M
from apps.forecasting import specs
from apps.forecasting.experiments import evaluate_predictions, start_run, write_json
from apps.forecasting.offline import ParquetHistory
from apps.forecasting.probability_calibration import (
    calibrated_predict,
    calibration_periods,
    choose_calibration,
    fit_calibrators,
    reliability_bins,
)


class Command(BaseCommand):
    help = "H08 probability calibration with disjoint early-stop/fit/selection periods"

    def add_arguments(self, parser):
        parser.add_argument("--snapshot", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--tasks", nargs="+", default=list(specs.SPECS), choices=list(specs.SPECS))

    def handle(self, *args, snapshot, output, tasks, **options):
        source = ParquetHistory(snapshot)
        start_run(
            output,
            source,
            "H08",
            tasks=tasks,
            selection="Q4_2025_Brier_then_log_loss",
            early_stop="2025-01-01/2025-03-30",
            calibration_fit="2025-04-01/2025-09-29",
            calibration_selection="2025-10-01/2025-12-30",
        )
        report = {}
        for task in tasks:
            started = time.monotonic()
            spec = specs.get(task)
            dataset, _, _ = M.build_dataset(spec, source=source)
            parts = M._split_dataset(dataset, 1)
            del dataset
            periods = calibration_periods(parts["valid"])
            columns = M.matrix_columns(spec.features)
            types = sorted(parts["train"]["sensor_type"].unique().to_list())
            train = parts["train"]
            early = periods["early_stop"]
            xy = {
                "train": (
                    M.to_matrix(train, types, columns),
                    train["y"].to_numpy(),
                    train["weight"].to_numpy(),
                ),
                "valid": (M.to_matrix(early, types, columns), early["y"].to_numpy(), np.ones(len(early))),
            }
            self.stdout.write(f"[{task}] fitting base with Q1-only early stopping")
            self.stdout.flush()
            booster = M._fit(xy, columns, M.PARAMS | spec.params)
            booster.save_model(output / f"{task}.txt")
            write_json(
                output / f"{task}.json",
                {"columns": columns, "sensor_types": types, "horizon_hours": 24, "task": task},
            )
            fit = periods["fit_calibration"]
            p_fit = booster.predict(M.to_matrix(fit, types, columns))
            calibrators = fit_calibrators(fit["y"].to_numpy(), p_fit)
            joblib.dump(calibrators, output / f"{task}_calibrators.joblib")
            select = periods["select_calibration"]
            p_select = booster.predict(M.to_matrix(select, types, columns))
            predictions = {
                "valid": {name: calibrated_predict(name, c, p_select) for name, c in calibrators.items()}
            }
            y_select = select["y"].to_numpy()
            selection = {
                name: {
                    "brier": float(brier_score_loss(y_select, p)),
                    "log_loss": float(log_loss(y_select, p, labels=[False, True])),
                }
                for name, p in predictions["valid"].items()
            }
            winner = choose_calibration(selection)
            write_json(output / f"{task}_selection.json", {"selected": winner, "Q4_2025": selection})
            # Diagnostic test is first used only after freezing the calibration choice.
            p_test = booster.predict(M.to_matrix(parts["test"], types, columns))
            predictions["test"] = {
                name: calibrated_predict(name, c, p_test) for name, c in calibrators.items()
            }
            evaluation_parts = {"valid": select, "test": parts["test"]}
            reliability = {}
            for part in ["valid", "test"]:
                frame = evaluation_parts[part]
                frame.select("channel_id", "day", "y").with_columns(
                    *[pl.Series(name, p) for name, p in predictions[part].items()]
                ).write_parquet(output / f"{task}_{part}_predictions.parquet")
                reliability[part] = {
                    name: reliability_bins(frame["y"].to_numpy(), p) for name, p in predictions[part].items()
                }
            report[task] = {
                "selected": winner,
                "selection": selection,
                "reliability": reliability,
                "models": evaluate_predictions(evaluation_parts, predictions),
                "base_best_iteration": booster.best_iteration,
                "sigmoid_slope": float(calibrators["sigmoid"].coef_[0, 0]),
                "rows": {
                    **{name: len(frame) for name, frame in periods.items()},
                    "train": len(train),
                    "test": len(parts["test"]),
                },
                "seconds": time.monotonic() - started,
            }
            write_json(output / "metrics.json", report)
            self.stdout.write(f"[{task}] COMPLETE selected={winner} {report[task]['seconds']:.1f}s")
            self.stdout.flush()
            del parts, periods, xy, predictions, booster, calibrators
