"""H02: fixed CatBoost depth/tree grid selected using external metrics on 2025 validation."""

import importlib.metadata
import json
import time
from pathlib import Path

import polars as pl
from django.core.management.base import BaseCommand, CommandError

from apps.forecasting import channel_model as M
from apps.forecasting import specs
from apps.forecasting.domain import features as F
from apps.forecasting.experiment_models import (
    CATBOOST_PARAMS,
    TREE_CHECKPOINTS,
    cat_frame,
    choose_trial,
    validation_trial,
)
from apps.forecasting.experiments import evaluate_predictions, reference_predictions, start_run, write_json
from apps.forecasting.offline import ParquetHistory


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
            params=CATBOOST_PARAMS,
            depths=[4, 6],
            tree_checkpoints=TREE_CHECKPOINTS,
            early_stopping="disabled; use external AP/recall, not CatBoost trapezoidal PRAUC",
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
                model = CatBoostClassifier(**CATBOOST_PARAMS, depth=depth)
                fit_start = time.monotonic()
                model.fit(train, eval_set=valid)
                fit_seconds = time.monotonic() - fit_start
                for trees in TREE_CHECKPOINTS:
                    p = model.predict_proba(valid, ntree_end=trees)[:, 1]
                    pv[depth, trees] = p
                    trials.append(
                        validation_trial(yv, p, parts["valid"]["day"].n_unique(), depth, trees)
                        | {"full_fit_seconds": fit_seconds}
                    )
                model.save_model(output / f"{task}_depth{depth}.cbm")
                del model
            winner = choose_trial(trials)
            write_json(output / f"{task}_selection.json", {"trials": trials, "selected": winner})
            # The selected candidate is frozen before constructing the test Pool.
            model = CatBoostClassifier()
            model.load_model(output / f"{task}_depth{winner['depth']}.cbm")
            model.shrink(ntree_end=winner["trees"])
            model.save_model(output / f"{task}_selected.cbm")
            predictions = reference_predictions(reference, task, parts)
            predictions["valid"]["catboost"] = pv[winner["depth"], winner["trees"]]
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
