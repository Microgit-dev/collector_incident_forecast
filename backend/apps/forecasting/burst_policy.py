"""H09b: causal rolling budgets and outcome-independent score-tie randomization."""

from dataclasses import dataclass

import numpy as np
import polars as pl

from .event_replay import AlertStream


@dataclass(frozen=True)
class BudgetPolicy:
    name: str
    threshold: float
    daily_budget: int = 20
    window_days: int = 1
    split_ties: bool = True
    seed: int = 42
    burst_limit: int | None = None

    def __post_init__(self):
        if self.daily_budget < 1 or self.window_days < 1 or not np.isfinite(self.threshold):
            raise ValueError("Finite threshold and positive budget/window required")
        if self.burst_limit is not None and self.burst_limit < 1:
            raise ValueError("Positive burst limit required")


class BudgetStream(AlertStream):
    """Scores are ranked within a day; every acceptance sees only past budget consumption."""

    def __init__(self, frame, scores):
        super().__init__(frame, scores)
        self.frame_keys = frame.select("channel_id", "day")
        self.hash_orders = {}

    def run_budget(self, policy, previous=None):
        history = dict(previous or {})
        if any(day >= int(self.days.min()) for day in history):
            raise ValueError("Budget state must precede replay period")
        if (
            sum(n for day, n in history.items() if day > int(self.days.min()) - policy.window_days)
            > policy.daily_budget * policy.window_days
        ):
            raise ValueError("Invalid carried budget state")
        if policy.split_ties:
            if policy.seed not in self.hash_orders:
                hashes = (
                    self.frame_keys.select(pl.struct("channel_id", "day").hash(seed=policy.seed))
                    .to_series()
                    .to_numpy()
                )
                self.hash_orders[policy.seed] = np.lexsort((self.channels, hashes, -self.scores, self.days))
            order = self.hash_orders[policy.seed]
        else:
            order = self.order
        selected = []
        peak_window = 0
        for start, end in zip(self.day_starts, self.day_ends, strict=True):
            indices = order[start:end]
            day = int(self.days[indices[0]])
            history = {d: n for d, n in history.items() if d > day - policy.window_days}
            available = policy.daily_budget * policy.window_days - sum(history.values())
            if policy.burst_limit is not None:
                available = min(available, policy.burst_limit)
            candidates = indices[self.scores[indices] >= policy.threshold]
            if policy.split_ties:
                accepted = candidates[:available]
            else:
                values = self.scores[candidates]
                ends = (
                    np.r_[np.flatnonzero(values[1:] != values[:-1]) + 1, len(values)] if len(values) else []
                )
                fitting = [stop for stop in ends if stop <= available]
                accepted = candidates[: fitting[-1]] if fitting else candidates[:0]
            selected.extend(accepted.tolist())
            history[day] = len(accepted)
            peak_window = max(peak_window, sum(history.values()))
            if sum(history.values()) > policy.daily_budget * policy.window_days:
                raise ValueError("Rolling budget violated")
        return np.asarray(selected, dtype=np.int64), history, {"max_alerts_in_rolling_window": peak_window}


def burst_grid(threshold, budget, seed=42):
    return [
        BudgetPolicy("threshold_day_hash", threshold, budget, seed=seed),
        BudgetPolicy("rank_day_hash", 0.0, budget, seed=seed),
        BudgetPolicy("threshold_week_group", threshold, budget, 7, split_ties=False, seed=seed),
        BudgetPolicy("threshold_week_hash", threshold, budget, 7, seed=seed),
        BudgetPolicy("threshold_week_burst3_hash", threshold, budget, 7, seed=seed, burst_limit=3 * budget),
    ]


def choose_budget_trial(trials, window_days):
    eligible = [r for r in trials if r["policy"]["seed"] == 42 and r["policy"]["window_days"] == window_days]
    if not eligible:
        raise ValueError("No primary-seed candidates for this budget window")
    return max(
        eligible,
        key=lambda r: (
            r["validation"]["onset_recall"],
            r["validation"]["onset_alert_precision"],
            -r["validation"]["alerts"],
        ),
    )
