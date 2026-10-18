"""H09: reuse frozen H10 forecasts to evaluate telemetry onsets and causal alert policies."""

import json
import time
from dataclasses import asdict
from pathlib import Path

import polars as pl
from django.core.management.base import BaseCommand, CommandError

from apps.forecasting import specs
from apps.forecasting.event_history import episodes_from_runs, prepare_events
from apps.forecasting.event_replay import (
    AlertPolicy,
    AlertStream,
    ReplayContext,
    choose_policy,
    forecast_period_end,
    policy_grid,
)
from apps.forecasting.experiments import start_run, write_json
from apps.forecasting.offline import ParquetHistory


class Command(BaseCommand):
    help = "H09: true telemetry state onsets, hard daily budgets, cooldown, and H1-only policy selection"

    def add_arguments(self, parser):
        for name in ("snapshot", "reference", "events", "output"):
            parser.add_argument(f"--{name}", type=Path, required=True)
        parser.add_argument(
            "--years", nargs="+", type=int, choices=[2023, 2024, 2025], default=[2023, 2024, 2025]
        )
        parser.add_argument("--budget", type=int, choices=[5, 20, 50], default=20)
        parser.add_argument("--episode-gap-minutes", type=int, default=30)

    def handle(
        self, *args, snapshot, reference, events, output, years, budget, episode_gap_minutes, **options
    ):
        if budget < 1 or episode_gap_minutes < 0:
            raise CommandError("Positive budget and nonnegative episode gap required")
        source = ParquetHistory(snapshot)
        ref_config = json.loads((reference / "config.json").read_text())
        if ref_config["snapshot_fingerprint"] != source.cache_key:
            raise CommandError("H10 reference snapshot differs")
        ref_metrics = json.loads((reference / "metrics.json").read_text())
        for year in years:
            if str(year) not in ref_metrics:
                raise CommandError(f"Reference has no complete fold {year}")
        provenance, ends = prepare_events(
            source, events, list(specs.SPECS.values()), through=max(years), progress=self.stdout.write
        )
        start_run(
            output,
            source,
            "H09",
            reference=str(reference.resolve()),
            reference_commit=ref_config["commit"],
            years=years,
            event_provenance=provenance,
            episode_gap_minutes=episode_gap_minutes,
            budget_per_task_per_day=budget,
            joint_maximum_per_day=budget * len(specs.SPECS),
            test_status="retrospective H2 2023/2024/2025; frozen H10 predictions; no 2026",
            selection="H1 onset recall, then onset-alert precision, then fewer alerts; hard-cap candidates only",
            outcome_window="[MSK midnight after feature day, next midnight); horizon 24h; lead measured separately",
            score_ties="whole score groups; deterministic channel ID representative for tied channels at one node",
            cooldown="updated only on emitted alerts; selected policy state from H1 carried into H2",
        )
        meta = source.load_meta()
        report, audit = {}, {}
        for task in specs.SPECS:
            days = pl.read_parquet(sorted(events.glob(f"{task}_*_days.parquet")))
            runs = pl.read_parquet(sorted(events.glob(f"{task}_*_runs.parquet")))
            episodes = episodes_from_runs(runs, meta, ends, task, episode_gap_minutes)
            episodes.write_parquet(output / f"{task}_episodes.parquet")
            days.write_parquet(output / f"{task}_event_days.parquet")
            audit[task] = {
                "event_messages": int(days["event_rows"].sum()),
                "positive_channel_days": len(days),
                "merged_episodes": len(episodes),
                "left_censored": int(episodes["left_censored"].sum()),
                "right_censored": int(episodes["right_censored"].sum()),
                "sensor_type_episodes": dict(episodes.group_by("sensor_type").len().iter_rows()),
            }
            for year in years:
                started = time.monotonic()
                folder = output / str(year)
                folder.mkdir(exist_ok=True)
                self.stdout.write(f"[{year}/{task}] validation policies")
                self.stdout.flush()
                validation = pl.read_parquet(reference / str(year) / f"{task}_valid_predictions.parquet")
                valid_end = forecast_period_end(validation)
                valid_episodes = episodes_from_runs(
                    runs, meta, ends, task, episode_gap_minutes, cutoff=valid_end
                )
                valid = ReplayContext(validation, meta, days, valid_episodes)
                valid.matches.write_parquet(folder / f"{task}_valid_episode_opportunities.parquet")
                models = [name for name in validation.columns if name not in ("channel_id", "day", "y")]
                trials, states, by_model = [], {}, {}
                for model in models:
                    threshold = ref_metrics[str(year)][task]["models"][model][str(budget)][
                        "threshold_from_validation"
                    ]
                    stream = AlertStream(valid.frame, validation[model].to_numpy())
                    model_trials = []
                    for policy in policy_grid(threshold, budget):
                        selected, state, diagnostics = stream.run(policy)
                        metric = valid.evaluate(selected)
                        if policy.daily_limit is not None and metric["max_alerts_per_day"] > budget:
                            raise ValueError("Hard daily alert limit violated")
                        trial = {"model": model, "policy": asdict(policy), "validation": metric | diagnostics}
                        states[model, policy.name] = state
                        model_trials.append(trial)
                    trials.extend(model_trials)
                    by_model[model] = choose_policy(model_trials)
                winner = choose_policy(trials)
                selection = {"selected": winner, "selected_per_model": by_model, "validation_trials": trials}
                write_json(folder / f"{task}_selection.json", selection)
                # Nothing from H2 is loaded until all candidate policies/model choices are frozen.
                test_predictions = pl.read_parquet(reference / str(year) / f"{task}_test_predictions.parquet")
                test_end = forecast_period_end(test_predictions)
                test_episodes = episodes_from_runs(
                    runs, meta, ends, task, episode_gap_minutes, cutoff=test_end
                )
                test = ReplayContext(test_predictions, meta, days, test_episodes)
                test.matches.write_parquet(folder / f"{task}_test_episode_opportunities.parquet")
                records = {}
                for model in models:
                    scores = test_predictions[model].to_numpy()
                    stream = AlertStream(test.frame, scores)
                    model_records = {}
                    for trial in [r for r in trials if r["model"] == model]:
                        policy = AlertPolicy(**trial["policy"])
                        selected, _, diagnostics = stream.run(policy, states[model, policy.name])
                        metric = test.evaluate(selected)
                        model_records[policy.name] = {
                            "validation": trial["validation"],
                            "test": metric | diagnostics,
                        }
                        if policy.daily_limit is not None and metric["max_alerts_per_day"] > budget:
                            raise ValueError("H2 hard daily limit violated")
                        test.alert_rows(selected, scores).write_parquet(
                            folder / f"{task}_{model}_{policy.name}_alerts.parquet"
                        )
                    records[model] = model_records
                task_report = {
                    "selection": {"model": winner["model"], "policy": winner["policy"]},
                    "selected_test": records[winner["model"]][winner["policy"]["name"]]["test"],
                    "policies": records,
                    "seconds": time.monotonic() - started,
                }
                report.setdefault(str(year), {})[task] = task_report
                write_json(output / "metrics.json", report)
                write_json(output / "event_audit.json", audit)
                self.stdout.write(
                    f"[{year}/{task}] COMPLETE {winner['model']}/{winner['policy']['name']} {task_report['seconds']:.1f}s"
                )
                self.stdout.flush()
                del validation, valid, test_predictions, test, stream
