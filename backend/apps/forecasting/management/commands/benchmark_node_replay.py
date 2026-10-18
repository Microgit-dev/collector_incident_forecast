"""H09c: channel encoders -> label-blind node head -> node-level event evaluation."""

import json
import time
from dataclasses import asdict
from pathlib import Path

import polars as pl
from django.core.management.base import BaseCommand, CommandError
from sklearn.metrics import average_precision_score

from apps.forecasting import specs
from apps.forecasting.burst_policy import BudgetPolicy, BudgetStream
from apps.forecasting.event_history import episodes_from_runs, prepare_events
from apps.forecasting.event_replay import forecast_period_end
from apps.forecasting.experiments import budget_threshold, start_run, write_json
from apps.forecasting.node_replay import (
    NodeReplayContext,
    aggregate_node_scores,
    choose_node_trial,
    cluster_node_onsets,
)
from apps.forecasting.offline import ParquetHistory


class Command(BaseCommand):
    help = "H09c: node max/mean/top3 heads versus constant/cardinality baselines; separate node budgets"

    def add_arguments(self, parser):
        for name in ("snapshot", "reference", "events", "output"):
            parser.add_argument(f"--{name}", type=Path, required=True)
        parser.add_argument("--budgets", nargs="+", type=int, choices=[5, 10, 20], default=[5, 10, 20])

    def handle(self, *args, snapshot, reference, events, output, budgets, **options):
        if 5 not in budgets:
            raise CommandError("Include the predeclared primary budget 5")
        source = ParquetHistory(snapshot)
        config = json.loads((reference / "config.json").read_text())
        if config["snapshot_fingerprint"] != source.cache_key:
            raise CommandError("Snapshot differs from H10")
        _, ends = prepare_events(
            source, events, list(specs.SPECS.values()), through=2025, progress=self.stdout.write
        )
        start_run(
            output,
            source,
            "H09c",
            reference=str(reference.resolve()),
            prediction_unit="node_day",
            event_unit="node_task_onset_cluster",
            channel_gap_minutes=30,
            node_gap_minutes=30,
            budgets_per_task_per_day=budgets,
            primary_budget=5,
            seed=42,
            score_semantics="ranking heads over eligible channel scores; NOT calibrated node probabilities",
            selection="H1 node-onset recall, then onset-alert precision, then fewer cards; includes baselines",
            test_status="retrospective H2 2023/2024/2025; different unit from channel replay; not independent",
        )
        meta, report = source.load_meta(), {}
        for year in (2023, 2024, 2025):
            folder = output / str(year)
            folder.mkdir()
            for task in specs.SPECS:
                started = time.monotonic()
                runs = pl.read_parquet(sorted(events.glob(f"{task}_*_runs.parquet")))
                valid_predictions = pl.read_parquet(
                    reference / str(year) / f"{task}_valid_predictions.parquet"
                )
                models = [c for c in valid_predictions.columns if c not in ("channel_id", "day", "y")]
                channel_episodes = episodes_from_runs(
                    runs, meta, ends, task, cutoff=forecast_period_end(valid_predictions)
                )
                valid_clusters = cluster_node_onsets(channel_episodes, task)
                valid_scores = aggregate_node_scores(valid_predictions, meta, models)
                valid = NodeReplayContext(valid_scores, valid_clusters)
                valid.matches.write_parquet(folder / f"{task}_valid_node_opportunities.parquet")
                valid.frame.drop("channel_id", "sensor_type").write_parquet(
                    folder / f"{task}_valid_node_scores.parquet"
                )
                heads = [
                    c
                    for c in valid_scores.columns
                    if c not in ("node_id", "day", "source_channels", "eligible_channels")
                ]
                trials = []
                for head in heads:
                    scores = valid.frame[head].to_numpy()
                    stream = BudgetStream(valid.frame, scores)
                    ap = float(average_precision_score(valid.frame["y"].to_numpy(), scores))
                    for budget in budgets:
                        threshold = budget_threshold(scores, budget * valid.exposure_days)
                        for name, floor in [("rank", 0.0), ("threshold", threshold)]:
                            policy = BudgetPolicy(name, floor, budget)
                            chosen, _, diagnostics = stream.run_budget(policy)
                            trials.append(
                                {
                                    "head": head,
                                    "budget": budget,
                                    "policy": asdict(policy),
                                    "validation_ap": ap,
                                    "validation": valid.evaluate(chosen) | diagnostics,
                                }
                            )
                winners = {
                    str(budget): choose_node_trial([r for r in trials if r["budget"] == budget])
                    for budget in budgets
                }
                write_json(
                    folder / f"{task}_selection.json", {"selected": winners, "validation_trials": trials}
                )
                # Node outcome construction and H2 scores are loaded only after H1 choices are frozen.
                test_predictions = pl.read_parquet(reference / str(year) / f"{task}_test_predictions.parquet")
                channel_episodes = episodes_from_runs(
                    runs, meta, ends, task, cutoff=forecast_period_end(test_predictions)
                )
                test_clusters = cluster_node_onsets(channel_episodes, task)
                test_scores = aggregate_node_scores(test_predictions, meta, models)
                test = NodeReplayContext(test_scores, test_clusters)
                test.matches.write_parquet(folder / f"{task}_test_node_opportunities.parquet")
                test.frame.drop("channel_id", "sensor_type").write_parquet(
                    folder / f"{task}_test_node_scores.parquet"
                )
                records = []
                for head in heads:
                    scores = test.frame[head].to_numpy()
                    stream = BudgetStream(test.frame, scores)
                    ap = float(average_precision_score(test.frame["y"].to_numpy(), scores))
                    for trial in [r for r in trials if r["head"] == head]:
                        policy = BudgetPolicy(**trial["policy"])
                        chosen, _, diagnostics = stream.run_budget(policy)
                        metric = test.evaluate(chosen) | diagnostics
                        if metric["max_alerts_per_day"] > policy.daily_budget:
                            raise ValueError("Node daily budget violated")
                        records.append(trial | {"test_ap": ap, "test": metric})
                        test.alert_rows(chosen, scores).write_parquet(
                            folder / f"{task}_{head}_{policy.name}_k{policy.daily_budget}_alerts.parquet"
                        )
                selected = {
                    budget: next(r for r in records if r["head"] == w["head"] and r["policy"] == w["policy"])
                    for budget, w in winners.items()
                }
                report.setdefault(str(year), {})[task] = {
                    "selected": selected,
                    "trials": records,
                    "validation_node_days": len(valid.frame),
                    "test_node_days": len(test.frame),
                    "test_nodes": test.frame["node_id"].n_unique(),
                    "seconds": time.monotonic() - started,
                }
                write_json(output / "metrics.json", report)
                self.stdout.write(
                    f"[{year}/{task}] COMPLETE k5={selected['5']['head']} {report[str(year)][task]['seconds']:.1f}s"
                )
                self.stdout.flush()
                del valid_predictions, test_predictions, valid, test, runs
