"""H05: remove only node context, preserving the H01 training and evaluation protocol."""

import json
import time
from pathlib import Path

import polars as pl
from django.core.management.base import BaseCommand, CommandError

from apps.forecasting import channel_model as M
from apps.forecasting import specs
from apps.forecasting.experiments import evaluate_predictions, reference_predictions, start_run, write_json
from apps.forecasting.offline import ParquetHistory


def without_node_context(columns):
    return [col for col in columns if not col.startswith("node_")]


class Command(BaseCommand):
    help = "H05 paired ablation of neighboring-channel features"

    def add_arguments(self, parser):
        parser.add_argument("--snapshot", type=Path, required=True)
        parser.add_argument("--reference", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--tasks", nargs="+", default=list(specs.SPECS), choices=list(specs.SPECS))

    def handle(self, *args, snapshot, reference, output, tasks, **options):
        source = ParquetHistory(snapshot)
        if json.loads((reference / "config.json").read_text())["snapshot_fingerprint"] != source.cache_key:
            raise CommandError("Reference snapshot differs")
        start_run(output, source, "H05", ablation="drop_node_features_only", tasks=tasks)
        report = {}
        for task in tasks:
            started = time.monotonic()
            spec = specs.get(task)
            dataset, _, _ = M.build_dataset(spec, source=source)
            parts = M._split_dataset(dataset, 1)
            del dataset
            columns = without_node_context(M.matrix_columns(spec.features))
            sensor_types = sorted(parts["train"]["sensor_type"].unique().to_list())
            xy = {
                part: (
                    M.to_matrix(frame, sensor_types, columns),
                    frame["y"].to_numpy(),
                    frame["weight"].to_numpy(),
                )
                for part, frame in parts.items()
            }
            self.stdout.write(f"[{task}] fitting without node context")
            self.stdout.flush()
            booster = M._fit(xy, columns, M.PARAMS | spec.params)
            booster.save_model(output / f"{task}.txt")
            write_json(
                output / f"{task}.json",
                {"columns": columns, "sensor_types": sensor_types, "horizon_hours": 24, "task": task},
            )
            predictions = reference_predictions(reference, task, parts, models=("lightgbm",))
            for part in ["valid", "test"]:
                predictions[part]["without_node_context"] = booster.predict(xy[part][0])
                parts[part].select("channel_id", "day", "y").with_columns(
                    *[pl.Series(name, p) for name, p in predictions[part].items()]
                ).write_parquet(output / f"{task}_{part}_predictions.parquet")
            report[task] = {
                "removed": [f for f in spec.features if f.startswith("node_")],
                "best_iteration": booster.best_iteration,
                "models": evaluate_predictions(parts, predictions),
                "seconds": time.monotonic() - started,
            }
            write_json(output / "metrics.json", report)
            self.stdout.write(f"[{task}] COMPLETE {report[task]['seconds']:.1f}s")
            self.stdout.flush()
            del parts, xy, predictions, booster
