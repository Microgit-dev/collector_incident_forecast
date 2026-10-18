"""H02: fixed two-trial CatBoost comparison; select only on 2025 validation."""

import importlib.metadata
import json
import time
from pathlib import Path

import numpy as np
import polars as pl
from django.core.management.base import BaseCommand, CommandError
from sklearn.metrics import average_precision_score

from apps.forecasting import channel_model as M
from apps.forecasting import specs
from apps.forecasting.domain import features as F
from apps.forecasting.experiments import evaluate_predictions, reference_predictions, start_run, write_json
from apps.forecasting.management.commands.benchmark_ml import budget_threshold
from apps.forecasting.offline import ParquetHistory

PARAMS = {
    "iterations": 400,
    "learning_rate": 0.05,
    "l2_leaf_reg": 3,
    "loss_function": "Logloss",
    "eval_metric": "PRAUC:type=Classic;use_weights=true",
    "early_stopping_rounds": 60,
    "random_seed": 42,
    "thread_count": 4,
    "task_type": "CPU",
    "allow_writing_files": False,
    "verbose": 50,
}


def cat_frame(frame, columns):
    result = frame.select(
        *[pl.col(c).cast(pl.Float32) for c in columns if c not in F.CATEGORICAL],
        *[pl.col(c).cast(pl.String) for c in F.CATEGORICAL],
    ).to_pandas()
    for col in F.CATEGORICAL:
        result[col] = result[col].astype("category")
    return result


def choose_trial(trials):
    return max(trials, key=lambda r: (r["validation_recall_at_20"], r["validation_ap"]))


class Command(BaseCommand):
    help = "H02 CatBoost vs H01, with identical data and no test-based tuning"

    def add_arguments(self, parser):
        parser.add_argument("--snapshot", type=Path, required=True)
        parser.add_argument("--reference", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--tasks", nargs="+", default=list(specs.SPECS), choices=list(specs.SPECS))

    def handle(self, *args, snapshot, reference, output, tasks, **options):
        from catboost import CatBoostClassifier, Pool

        source = ParquetHistory(snapshot)
        ref_config = json.loads((reference / "config.json").read_text())
        if ref_config["snapshot_fingerprint"] != source.cache_key:
            raise CommandError("Reference snapshot differs")
        start_run(
            output,
            source,
            "H02",
            params=PARAMS,
            depths=[4, 6],
            selection="validation_recall_at_20_then_AP",
            catboost=importlib.metadata.version("catboost"),
        )
        report = {}
        for task in tasks:
            started = time.monotonic()
            spec = specs.get(task)
            dataset, _, _ = M.build_dataset(spec, source=source)
            parts = M._split_dataset(dataset, 1)
            del dataset
            columns = M.matrix_columns(spec.features)
            train = Pool(
                cat_frame(parts["train"], columns),
                parts["train"]["y"].to_numpy(),
                weight=parts["train"]["weight"].to_numpy(),
                cat_features=F.CATEGORICAL,
            )
            valid = Pool(
                cat_frame(parts["valid"], columns), parts["valid"]["y"].to_numpy(), cat_features=F.CATEGORICAL
            )
            yv = parts["valid"]["y"].to_numpy()
            trials = []
            pv = {}
            for depth in [4, 6]:
                self.stdout.write(f"[{task}] depth={depth}")
                self.stdout.flush()
                model = CatBoostClassifier(**PARAMS, depth=depth)
                fit_start = time.monotonic()
                model.fit(train, eval_set=valid)
                p = model.predict_proba(valid)[:, 1]
                pv[depth] = p
                threshold = budget_threshold(p, 20 * parts["valid"]["day"].n_unique())
                _, recall = M._pr(yv, p >= threshold, np.ones(len(yv)))
                trials.append(
                    {
                        "depth": depth,
                        "validation_recall_at_20": recall,
                        "validation_ap": float(average_precision_score(yv, p)),
                        "trees": model.tree_count_,
                        "fit_seconds": time.monotonic() - fit_start,
                    }
                )
                model.save_model(output / f"{task}_depth{depth}.cbm")
                del model
            winner = choose_trial(trials)
            write_json(output / f"{task}_selection.json", {"trials": trials, "selected": winner})
            # The selected candidate is frozen before constructing the test Pool.
            model = CatBoostClassifier()
            model.load_model(output / f"{task}_depth{winner['depth']}.cbm")
            predictions = reference_predictions(reference, task, parts)
            predictions["valid"]["catboost"] = pv[winner["depth"]]
            predictions["test"]["catboost"] = model.predict_proba(
                Pool(cat_frame(parts["test"], columns), cat_features=F.CATEGORICAL)
            )[:, 1]
            for part in ["valid", "test"]:
                parts[part].select("channel_id", "day", "y").with_columns(
                    *[pl.Series(name, p) for name, p in predictions[part].items()]
                ).write_parquet(output / f"{task}_{part}_predictions.parquet")
            report[task] = {
                "trials": trials,
                "selected": winner,
                "models": evaluate_predictions(parts, predictions),
                "seconds": time.monotonic() - started,
            }
            write_json(output / "metrics.json", report)
            self.stdout.write(f"[{task}] COMPLETE depth={winner['depth']} {report[task]['seconds']:.1f}s")
            self.stdout.flush()
            del parts, train, valid, predictions, model, pv
