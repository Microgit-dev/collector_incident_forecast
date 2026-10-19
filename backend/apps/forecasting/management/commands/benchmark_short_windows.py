"""H03: add strictly historical intraday features to the H01 LightGBM baseline."""

import json
import time
from pathlib import Path

import polars as pl
from django.core.management.base import BaseCommand, CommandError

from apps.forecasting import channel_model as M
from apps.forecasting import short_windows as W
from apps.forecasting import specs
from apps.forecasting.experiments import evaluate_predictions, reference_predictions, start_run, write_json
from apps.forecasting.offline import ParquetHistory


class Command(BaseCommand):
    help = "H03: short historical windows versus the daily-only baseline"

    def add_arguments(self, parser):
        for name in ("snapshot", "reference", "output", "windows"):
            parser.add_argument(f"--{name}", type=Path, required=True)
        parser.add_argument("--tasks", nargs="+", default=list(specs.SPECS), choices=list(specs.SPECS))

    def handle(self, *args, snapshot, reference, output, windows, tasks, **options):
        source = ParquetHistory(snapshot)
        if json.loads((reference / "config.json").read_text())["snapshot_fingerprint"] != source.cache_key:
            raise CommandError("Reference snapshot differs")
        provenance = W.prepare_windows(source, windows, self.stdout.write)
        start_run(
            output,
            source,
            "H03",
            window_provenance=provenance,
            as_of="00:00 Europe/Moscow; features [as_of-h,as_of); target next 24h",
            added_features=W.FEATURES,
            selection="validation only; fixed H01 LightGBM parameters",
        )
        report = {}
        for task in tasks:
            started = time.monotonic()
            spec = specs.get(task)
            dataset, _, _ = M.build_dataset(spec, source=source)
            ids = dataset["channel_id"].unique()
            short = (
                pl.scan_parquet(sorted(windows.glob("short_*.parquet")))
                .filter(pl.col("channel_id").is_in(ids.implode()))
                .collect(engine="streaming")
            )
            dataset = W.attach_windows(dataset, short)
            del short
            parts = M._split_dataset(dataset, 1)
            del dataset
            columns = M.matrix_columns([*spec.features, *W.FEATURES])
            types = sorted(parts["train"]["sensor_type"].unique().to_list())
            xy = {
                name: (M.to_matrix(frame, types, columns), frame["y"].to_numpy(), frame["weight"].to_numpy())
                for name, frame in parts.items()
            }
            self.stdout.write(f"[{task}] fitting daily + short windows")
            self.stdout.flush()
            model = M._fit(xy, columns, M.PARAMS | spec.params)
            model.save_model(output / f"{task}.txt")
            write_json(
                output / f"{task}.json", {"columns": columns, "sensor_types": types, "horizon_hours": 24}
            )
            predictions = reference_predictions(reference, task, parts, models=("lightgbm",))
            for name in ("valid", "test"):
                predictions[name]["short_windows"] = model.predict(xy[name][0])
                parts[name].select("channel_id", "day", "y").with_columns(
                    *[pl.Series(col, p) for col, p in predictions[name].items()]
                ).write_parquet(output / f"{task}_{name}_predictions.parquet")
            report[task] = {
                "models": evaluate_predictions(parts, predictions),
                "best_iteration": model.best_iteration,
                "importance_gain": dict(
                    zip(columns, model.feature_importance(importance_type="gain").tolist(), strict=True)
                ),
                "seconds": time.monotonic() - started,
            }
            write_json(output / "metrics.json", report)
            self.stdout.write(f"[{task}] COMPLETE {report[task]['seconds']:.1f}s")
            self.stdout.flush()
            del parts, xy, predictions, model
