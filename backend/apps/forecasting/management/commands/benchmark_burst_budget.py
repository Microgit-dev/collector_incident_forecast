"""H09b: isolate tied-score budget loss and test causal burst reserves on frozen H09 facts."""

import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.forecasting import specs
from apps.forecasting.burst_policy import BudgetPolicy, BudgetStream, burst_grid, choose_budget_trial
from apps.forecasting.experiments import start_run, write_json
from apps.forecasting.offline import ParquetHistory
from apps.forecasting.replay_io import load_frozen_replay


class Command(BaseCommand):
    help = "H09b: hash tie breaks and rolling 7-day budgets; reuse frozen H09 event definitions"

    def add_arguments(self, parser):
        for name in ("snapshot", "reference", "events-run", "output"):
            parser.add_argument(f"--{name}", type=Path, required=True)
        parser.add_argument("--budget", type=int, choices=[5, 20, 50], default=20)

    def handle(self, *args, snapshot, reference, events_run, output, budget, **options):
        source = ParquetHistory(snapshot)
        config = json.loads((events_run / "config.json").read_text())
        if config["snapshot_fingerprint"] != source.cache_key or config["budget_per_task_per_day"] != budget:
            raise CommandError("H09 snapshot or budget differs")
        if Path(config["reference"]).resolve() != reference.resolve():
            raise CommandError("H10 reference differs from frozen H09 run")
        baseline = json.loads((reference / "metrics.json").read_text())
        start_run(
            output,
            source,
            "H09b",
            reference=str(reference.resolve()),
            events_run=str(events_run.resolve()),
            h09_config_sha256=hashlib.sha256((events_run / "config.json").read_bytes()).hexdigest(),
            primary_seed=42,
            tie_sensitivity_seeds=[43, 44],
            daily_budget=budget,
            rolling_budget=7 * budget,
            selection="H1 only; primary seed42; separate winners for daily and weekly constraints",
            test_status="retrospective extension motivated by H09; same old H2 periods, not an independent test",
            tie_break="Polars hash(channel_id,feature_day,seed), never outcomes; score priority unchanged",
        )
        meta, report = source.load_meta(), {}
        for year in config["years"]:
            folder = output / str(year)
            folder.mkdir()
            for task in specs.SPECS:
                started = time.monotonic()
                predictions, valid = load_frozen_replay(reference, events_run, year, task, "valid", meta)
                models = [c for c in predictions.columns if c not in ("channel_id", "day", "y")]
                trials, states = [], {}
                for model in models:
                    threshold = baseline[str(year)][task]["models"][model][str(budget)][
                        "threshold_from_validation"
                    ]
                    stream = BudgetStream(valid.frame, predictions[model].to_numpy())
                    for seed in (42, 43, 44):
                        for policy in burst_grid(threshold, budget, seed):
                            if seed != 42 and not policy.split_ties:
                                continue  # seed cannot change whole-group ties
                            selected, state, diagnostics = stream.run_budget(policy)
                            trial = {
                                "model": model,
                                "policy": asdict(policy),
                                "validation": valid.evaluate(selected) | diagnostics,
                            }
                            trials.append(trial)
                            states[model, policy.name, seed] = state
                winners = {str(window): choose_budget_trial(trials, window) for window in (1, 7)}
                write_json(
                    folder / f"{task}_selection.json", {"selected": winners, "validation_trials": trials}
                )
                # Evaluate H2 only after both budget-family choices have been saved.
                predictions, test = load_frozen_replay(reference, events_run, year, task, "test", meta)
                records = []
                for model in models:
                    scores = predictions[model].to_numpy()
                    stream = BudgetStream(test.frame, scores)
                    for trial in [t for t in trials if t["model"] == model]:
                        policy = BudgetPolicy(**trial["policy"])
                        selected, _, diagnostics = stream.run_budget(
                            policy, states[model, policy.name, policy.seed]
                        )
                        metric = test.evaluate(selected) | diagnostics
                        records.append(
                            {
                                "model": model,
                                "policy": asdict(policy),
                                "validation": trial["validation"],
                                "test": metric,
                            }
                        )
                        test.alert_rows(selected, scores).write_parquet(
                            folder / f"{task}_{model}_{policy.name}_seed{policy.seed}_alerts.parquet"
                        )
                chosen = {}
                for window, winner in winners.items():
                    chosen[window] = next(
                        r
                        for r in records
                        if r["model"] == winner["model"] and r["policy"] == winner["policy"]
                    )
                report.setdefault(str(year), {})[task] = {
                    "selected": chosen,
                    "trials": records,
                    "seconds": time.monotonic() - started,
                }
                write_json(output / "metrics.json", report)
                self.stdout.write(f"[{year}/{task}] COMPLETE {report[str(year)][task]['seconds']:.1f}s")
                self.stdout.flush()
                del valid, test, predictions, stream
