"""H10: rolling temporal stress check of algorithms and H03 features, excluding 2026."""

import time
from datetime import timedelta
from pathlib import Path

import joblib
import polars as pl
from django.core.management.base import BaseCommand

from apps.forecasting import channel_model as M
from apps.forecasting import short_windows as W
from apps.forecasting import specs
from apps.forecasting.domain import features as F
from apps.forecasting.experiments import evaluate_predictions, start_run, write_json
from apps.forecasting.management.commands.benchmark_catboost import (
    PARAMS,
    TREE_CHECKPOINTS,
    cat_frame,
    choose_trial,
    validation_trial,
)
from apps.forecasting.management.commands.benchmark_ml import predict_batches
from apps.forecasting.offline import ParquetHistory
from apps.forecasting.temporal_validation import TemporalFold, TemporalHistory, logistic_pipeline


class Command(BaseCommand):
    help = "H10: train through previous year, tune H1, evaluate H2, for 2023/2024/2025"

    def add_arguments(self, parser):
        for name in ("snapshot", "windows", "output"):
            parser.add_argument(f"--{name}", type=Path, required=True)
        parser.add_argument(
            "--years", nargs="+", type=int, choices=[2023, 2024, 2025], default=[2023, 2024, 2025]
        )
        parser.add_argument("--tasks", nargs="+", default=list(specs.SPECS), choices=list(specs.SPECS))

    def handle(self, *args, snapshot, windows, output, years, tasks, **options):
        from catboost import CatBoostClassifier, Pool

        source = ParquetHistory(snapshot)
        provenance = W.prepare_windows(source, windows, self.stdout.write)
        start_run(
            output,
            source,
            "H10",
            years=years,
            tasks=tasks,
            window_provenance=provenance,
            test_status="retrospective rolling H2 2023/2024/2025; 2026 excluded; not an untouched benchmark",
            protocol="train before Jan1; validation H1; evaluation H2; purge entire label horizon at boundaries",
            models=["logistic", "lightgbm", "short_windows", "catboost"],
            selection="LGBM early stopping AP; CatBoost fixed depth6, checkpoints selected by H1 recall@20 then AP",
            catboost_params=PARAMS | {"depth": 6},
        )
        report = {}
        for year in years:
            fold = TemporalFold(year)
            history = TemporalHistory(snapshot, fold.end - timedelta(days=1))
            folder = output / str(year)
            folder.mkdir()
            fold_report = {}
            for task in tasks:
                started = time.monotonic()
                spec = specs.get(task)
                self.stdout.write(f"[{year}/{task}] building temporally restricted dataset")
                self.stdout.flush()
                dataset, _, _ = M.build_dataset(spec, source=history, train_before=fold.valid_from)
                parts = fold.split(dataset)
                del dataset
                for name, frame in parts.items():
                    if frame.is_empty() or frame["y"].n_unique() != 2:
                        raise ValueError(f"{year}/{task}/{name}: two label classes required")
                    if name != "train" and frame["weight"].unique().to_list() != [1.0]:
                        raise ValueError("Temporal validation/evaluation must retain unit weights")
                columns = M.matrix_columns(spec.features)
                types = sorted(parts["train"]["sensor_type"].unique().to_list())
                xy = {
                    name: (
                        M.to_matrix(frame, types, columns),
                        frame["y"].to_numpy(),
                        frame["weight"].to_numpy(),
                    )
                    for name, frame in parts.items()
                }
                predictions = {name: {} for name in ("valid", "test")}
                metadata = {"columns": columns, "sensor_types": types, "selected": {}}
                logistic = logistic_pipeline(columns)
                self.stdout.write(f"[{year}/{task}] logistic / LightGBM")
                self.stdout.flush()
                logistic.fit(xy["train"][0], xy["train"][1], classifier__sample_weight=xy["train"][2])
                joblib.dump(logistic, folder / f"{task}_logistic.joblib")
                metadata["logistic_iterations"] = logistic["classifier"].n_iter_.tolist()
                for name in predictions:
                    predictions[name]["logistic"] = predict_batches(logistic, xy[name][0])
                del logistic
                model = M._fit(xy, columns, M.PARAMS | spec.params)
                model.save_model(folder / f"{task}_lightgbm.txt")
                metadata["selected"]["lightgbm_iteration"] = model.best_iteration
                write_json(folder / f"{task}_selection.json", metadata)
                for name in predictions:
                    predictions[name]["lightgbm"] = model.predict(xy[name][0])
                del model, xy

                self.stdout.write(f"[{year}/{task}] short-window LightGBM")
                self.stdout.flush()
                ids = pl.concat([frame["channel_id"] for frame in parts.values()]).unique()
                short = (
                    pl.scan_parquet([windows / f"short_{y}.parquet" for y in history.years])
                    .filter(pl.col("channel_id").is_in(ids.implode()) & (pl.col("day") < fold.end))
                    .collect(engine="streaming")
                )
                extended = {name: W.attach_windows(frame, short) for name, frame in parts.items()}
                del short
                short_columns = M.matrix_columns([*spec.features, *W.FEATURES])
                xy_short = {
                    name: (
                        M.to_matrix(frame, types, short_columns),
                        frame["y"].to_numpy(),
                        frame["weight"].to_numpy(),
                    )
                    for name, frame in extended.items()
                }
                del extended
                model = M._fit(xy_short, short_columns, M.PARAMS | spec.params)
                model.save_model(folder / f"{task}_short_windows.txt")
                metadata["short_columns"] = short_columns
                metadata["selected"]["short_windows_iteration"] = model.best_iteration
                write_json(folder / f"{task}_selection.json", metadata)
                for name in predictions:
                    predictions[name]["short_windows"] = model.predict(xy_short[name][0])
                del xy_short, model

                self.stdout.write(f"[{year}/{task}] CatBoost depth6")
                self.stdout.flush()
                train = Pool(
                    cat_frame(parts["train"], columns),
                    parts["train"]["y"].to_numpy(),
                    weight=parts["train"]["weight"].to_numpy(),
                    cat_features=F.CATEGORICAL,
                )
                valid = Pool(
                    cat_frame(parts["valid"], columns),
                    parts["valid"]["y"].to_numpy(),
                    cat_features=F.CATEGORICAL,
                )
                model = CatBoostClassifier(**PARAMS, depth=6)
                model.fit(train, eval_set=valid)
                trials, candidate_predictions = [], {}
                for trees in TREE_CHECKPOINTS:
                    pv = model.predict_proba(valid, ntree_end=trees)[:, 1]
                    candidate_predictions[trees] = pv
                    trials.append(
                        validation_trial(
                            parts["valid"]["y"].to_numpy(), pv, parts["valid"]["day"].n_unique(), 6, trees
                        )
                    )
                winner = choose_trial(trials)
                metadata["selected"]["catboost"] = winner
                metadata["catboost_trials"] = trials
                write_json(folder / f"{task}_selection.json", metadata)
                model.shrink(ntree_end=winner["trees"])
                model.save_model(folder / f"{task}_catboost.cbm")
                predictions["valid"]["catboost"] = candidate_predictions[winner["trees"]]
                predictions["test"]["catboost"] = model.predict_proba(
                    Pool(cat_frame(parts["test"], columns), cat_features=F.CATEGORICAL)
                )[:, 1]
                del model, train, valid, candidate_predictions
                for name in predictions:
                    parts[name].select("channel_id", "day", "y").with_columns(
                        *[pl.Series(col, p) for col, p in predictions[name].items()]
                    ).write_parquet(folder / f"{task}_{name}_predictions.parquet")
                fold_report[task] = {
                    "rows": {name: len(frame) for name, frame in parts.items()},
                    "positives": {name: int(frame["y"].sum()) for name, frame in parts.items()},
                    "dates": {
                        name: [str(frame["day"].min()), str(frame["day"].max())]
                        for name, frame in parts.items()
                    },
                    "models": evaluate_predictions(parts, predictions),
                    "selection": metadata,
                    "seconds": time.monotonic() - started,
                }
                report[str(year)] = fold_report
                write_json(folder / "metrics.json", fold_report)
                write_json(output / "metrics.json", report)
                self.stdout.write(f"[{year}/{task}] COMPLETE {fold_report[task]['seconds']:.1f}s")
                self.stdout.flush()
                del parts, predictions
