"""Causal daily alert policies and telemetry-onset evaluation; policies never receive labels."""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl


def forecast_period_end(frame):
    """Exclusive UTC end of the last 24h outcome window, not the feature-day boundary."""
    last = frame["day"].max()
    if last is None:
        raise ValueError("Forecast period is empty")
    return datetime.combine(last + timedelta(days=2), time(), ZoneInfo("Europe/Moscow")).astimezone(UTC)


@dataclass(frozen=True)
class AlertPolicy:
    name: str
    threshold: float
    daily_limit: int | None = None
    cooldown_hours: int = 0
    one_per_node: bool = False

    def __post_init__(self):
        if not np.isfinite(self.threshold):
            raise ValueError("Finite threshold required")
        if self.daily_limit is not None and self.daily_limit < 1:
            raise ValueError("Positive daily limit required")
        if self.cooldown_hours < 0:
            raise ValueError("Nonnegative cooldown required")


class AlertStream:
    """Chronologically ordered known scores/metadata. No outcome or event inputs."""

    def __init__(self, frame, scores):
        self.scores = np.asarray(scores, dtype=float)
        if len(self.scores) != len(frame) or not np.isfinite(self.scores).all():
            raise ValueError("One finite score required per forecast")
        if ((self.scores < 0) | (self.scores > 1)).any():
            raise ValueError("Expected probability scores in [0,1]")
        if frame.select("channel_id", "day").is_duplicated().any():
            raise ValueError("Duplicate channel/day forecasts")
        if frame.is_empty() or frame.select("channel_id", "node_id", "day").null_count().to_numpy().sum():
            raise ValueError("Nonempty stream with complete IDs/dates required")
        self.channels = frame["channel_id"].to_numpy()
        self.nodes = frame["node_id"].to_numpy()
        self.days = frame["day"].cast(pl.Int32).to_numpy() + 1  # target date / issued-at midnight MSK
        self.unique_channels, self.channel_codes = np.unique(self.channels, return_inverse=True)
        self.order = np.lexsort((self.channels, -self.scores, self.days))
        ordered_days = self.days[self.order]
        self.day_starts = np.r_[0, np.flatnonzero(ordered_days[1:] != ordered_days[:-1]) + 1]
        self.day_ends = np.r_[self.day_starts[1:], len(self.order)]

    def run(self, policy, previous=None):
        # Using target-day ordinals is exact for the fixed daily MSK schedule in these journals.
        # Units are hours, so 48h/72h boundaries are inclusive without rounding dates.
        initial = dict(previous or {})
        first_hour = int(self.days.min()) * 24
        if any(hour >= first_hour for hour in initial.values()):
            raise ValueError("Cooldown state must precede the replay period")
        last = np.array([initial.get(int(ch), -(10**12)) for ch in self.unique_channels], dtype=np.int64)
        selected = []
        tied_budget_blocks = 0
        for start, end in zip(self.day_starts, self.day_ends, strict=True):
            ordered = self.order[start:end]
            hour = int(self.days[ordered[0]]) * 24
            scores = self.scores[ordered]
            stops = np.r_[np.flatnonzero(scores[1:] != scores[:-1]) + 1, len(ordered)]
            emitted, seen_nodes, cursor = 0, set(), 0
            for stop in stops:
                group = ordered[cursor:stop]
                cursor = stop
                if self.scores[group[0]] < policy.threshold:
                    break
                group = group[hour - last[self.channel_codes[group]] >= policy.cooldown_hours]
                if policy.one_per_node:
                    group = np.array(
                        [i for i in group if int(self.nodes[i]) not in seen_nodes], dtype=np.int64
                    )
                    if len(group):
                        _, first = np.unique(self.nodes[group], return_index=True)
                        group = group[np.sort(first)]  # deterministic channel-ID tie break within a node
                if policy.daily_limit is not None and emitted + len(group) > policy.daily_limit:
                    tied_budget_blocks += 1
                    break  # never split a tied group or skip it in favor of lower scores
                selected.extend(group.tolist())
                last[self.channel_codes[group]] = hour
                emitted += len(group)
                if policy.one_per_node:
                    seen_nodes.update(int(node) for node in self.nodes[group])
                if emitted == policy.daily_limit:
                    break
        state = initial | {
            int(ch): int(hour)
            for ch, hour in zip(self.unique_channels, last, strict=True)
            if hour > -(10**12)
        }
        return (
            np.asarray(selected, dtype=np.int64),
            state,
            {"tied_groups_blocked_by_budget": tied_budget_blocks},
        )


def policy_grid(threshold, budget):
    return [
        AlertPolicy("original_threshold", threshold),
        AlertPolicy("threshold_cap", threshold, budget),
        AlertPolicy("rank_cap", 0.0, budget),
        *[
            AlertPolicy(f"{mode}_cap_cd{hours}", floor, budget, hours)
            for mode, floor in [("threshold", threshold), ("rank", 0.0)]
            for hours in (48, 72)
        ],
        AlertPolicy("threshold_cap_node", threshold, budget, one_per_node=True),
    ]


class ReplayContext:
    """Bind event-day targets and onset opportunities once; evaluate many label-blind policies."""

    def __init__(self, predictions, meta, days, episodes):
        self.frame = predictions.join(
            meta.select("channel_id", "node_id", "sensor_type"),
            on="channel_id",
            how="left",
            validate="m:1",
            maintain_order="left",
        ).with_row_index("row_index")
        self.frame = self.frame.with_columns(
            (pl.col("day") + timedelta(days=1)).alias("target_day"),
        ).with_columns(
            pl.col("target_day")
            .cast(pl.Datetime("us"))
            .dt.replace_time_zone("Europe/Moscow")
            .dt.convert_time_zone("UTC")
            .alias("issued_at")
        )
        self.frame = self.frame.join(
            days.select("channel_id", pl.col("day").alias("target_day"), "event_rows"),
            on=["channel_id", "target_day"],
            how="left",
            validate="m:1",
            maintain_order="left",
        ).with_columns(pl.col("event_rows").fill_null(0))
        if self.frame.filter(pl.col("y") != (pl.col("event_rows") > 0)).height:
            raise ValueError("Saved labels disagree with raw-journal event-day facts")
        lo, hi = self.frame["issued_at"].min(), self.frame["issued_at"].max() + timedelta(days=1)
        self.exposure_days = (hi - lo).days
        in_period = episodes.filter((pl.col("start_at") >= lo) & (pl.col("start_at") < hi))
        self.censored = int(in_period["left_censored"].sum())
        self.episodes = in_period.filter(~pl.col("left_censored"))
        self.matches = (
            self.episodes.with_columns(
                pl.col("start_at").dt.convert_time_zone("Europe/Moscow").dt.date().alias("target_day")
            )
            .join(
                self.frame.select("channel_id", "target_day", "row_index", "issued_at"),
                on=["channel_id", "target_day"],
                how="left",
                validate="m:1",
            )
            .with_columns(
                ((pl.col("start_at") - pl.col("issued_at")).dt.total_microseconds() / 3.6e9).alias(
                    "lead_hours"
                )
            )
        )
        self.available = self.matches.filter(pl.col("row_index").is_not_null())
        self.onset_counts = np.bincount(
            self.available["row_index"].to_numpy().astype(int), minlength=len(self.frame)
        )

    def evaluate(self, selected):
        count = len(selected)
        detected = self.available.filter(pl.col("row_index").is_in(pl.Series(selected).implode()))
        hits = int((self.onset_counts[selected] > 0).sum())
        y = self.frame["y"].to_numpy()[selected]
        days = self.frame["target_day"].cast(pl.Int32).to_numpy()[selected]
        # pl.Date uses Unix epoch day numbers, independent of Python's ordinal origin.
        base = self.frame["target_day"].cast(pl.Int32).min()
        counts = np.bincount(days - base, minlength=self.exposure_days)
        event_count, opportunities = len(self.episodes), len(self.available)
        lead = detected["lead_hours"].to_numpy()
        result = {
            "alerts": count,
            "alerts_per_day": count / self.exposure_days,
            "max_alerts_per_day": int(counts.max()),
            "p95_alerts_per_day": float(np.percentile(counts, 95)),
            "onsets": event_count,
            "onsets_with_forecast_opportunity": opportunities,
            "onsets_without_forecast_opportunity": event_count - opportunities,
            "left_censored_onsets_excluded": self.censored,
            "detected_onsets": len(detected),
            "onset_recall": len(detected) / event_count if event_count else 0.0,
            "forecastable_onset_recall": len(detected) / opportunities if opportunities else 0.0,
            "onset_alert_precision": hits / count if count else 0.0,
            "journal_event_precision": float(y.mean()) if count else 0.0,
            "alerts_with_new_onset": hits,
            "alerts_with_event_but_no_new_onset": int(y.sum()) - hits,
            "alerts_without_journal_event": int((~y).sum()),
            "false_alerts_per_day": float((~y).sum()) / self.exposure_days,
            "lead_hours": (
                {
                    "median": float(np.median(lead)),
                    "p10": float(np.percentile(lead, 10)),
                    "p90": float(np.percentile(lead, 90)),
                }
                if len(lead)
                else None
            ),
            "onset_recall_min_lead": {
                str(h): float((lead >= h).sum()) / event_count if event_count else 0.0 for h in (1, 6, 12, 24)
            },
        }
        return result

    def alert_rows(self, selected, scores):
        return (
            self.frame[selected]
            .with_columns(
                pl.Series("score", np.asarray(scores)[selected]),
                pl.Series("new_onsets", self.onset_counts[selected]),
            )
            .select(
                "channel_id", "node_id", "sensor_type", "issued_at", "target_day", "score", "y", "new_onsets"
            )
        )


def choose_policy(trials):
    """Validation-only ordering. Original unbounded threshold is a comparator, never a winner."""
    eligible = [r for r in trials if r["policy"]["daily_limit"] is not None]
    return max(
        eligible,
        key=lambda r: (
            r["validation"]["onset_recall"],
            r["validation"]["onset_alert_precision"],
            -r["validation"]["alerts"],
        ),
    )
