from datetime import UTC, date, datetime

import numpy as np
import polars as pl

from apps.forecasting.channel_model import pick_threshold
from apps.forecasting.domain import features as F


def _daily(rows):
    base = {
        "readings": 1,
        "warnings": 0,
        "alarms": 0,
        "faults": 0,
        "power_losses": 0,
        "unknowns": 0,
        "invalid": 0,
        "numeric_avg": None,
        "numeric_min": None,
        "numeric_max": None,
        "last_state": "normal",
        "first_fault_ts": None,
    }
    return pl.DataFrame([base | r for r in rows]).with_columns(
        pl.col("readings", "warnings", "alarms", "faults", "power_losses", "unknowns", "invalid").cast(
            pl.Int32
        ),
        pl.col("numeric_avg", "numeric_min", "numeric_max").cast(pl.Float64),
        pl.col("first_fault_ts").cast(pl.Datetime("us", "UTC")),
    )


META = pl.DataFrame(
    {"channel_id": [1], "node_id": [10], "sensor_type": ["Датчик дыма"], "first_day": [date(2024, 1, 1)]}
)
NODES = pl.DataFrame(
    schema={"node_id": pl.Int64, "day": pl.Date, "node_faults": pl.Int32, "node_power": pl.Int32}
)


def test_grid_carries_state_through_silent_days():
    daily = _daily(
        [
            {"channel_id": 1, "day": date(2024, 1, 1)},
            {"channel_id": 1, "day": date(2024, 1, 3), "faults": 2, "last_state": "fault"},
        ]
    )
    grid = F.build_grid(daily, date(2024, 1, 5))
    assert grid["day"].to_list() == [date(2024, 1, d) for d in range(1, 6)]
    assert grid["last_state"].to_list() == ["normal", "normal", "fault", "fault", "fault"]
    assert grid["readings"].to_list() == [1, 0, 1, 0, 0]


def test_label_is_next_day_fault_onset_for_healthy_channels_only():
    daily = _daily(
        [
            {"channel_id": 1, "day": date(2024, 1, 1)},
            {"channel_id": 1, "day": date(2024, 1, 2)},
            {
                "channel_id": 1,
                "day": date(2024, 1, 3),
                "faults": 1,
                "last_state": "fault",
                "first_fault_ts": datetime(2024, 1, 3, 5, tzinfo=UTC),
            },
            {"channel_id": 1, "day": date(2024, 1, 4), "last_state": "normal"},
        ]
    )
    feats = F.compute_features(F.build_grid(daily, date(2024, 1, 5)), NODES, META)
    labelled = F.with_label(feats)
    # 3 января канал неисправен на конец суток — не прогнозируется; 5 января — нет следующих суток
    assert labelled["day"].to_list() == [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 4)]
    assert labelled["y"].to_list() == [False, True, False]
    row = labelled.filter(pl.col("day") == date(2024, 1, 4)).row(0, named=True)
    assert row["faults_7"] == 1 and row["days_since_fault"] == 1 and row["fault_days_30"] == 1


def test_excluded_year_splits_windows():
    daily = _daily(
        [
            {"channel_id": 1, "day": date(2020, 12, 31), "faults": 5},
            {"channel_id": 1, "day": date(2022, 1, 1)},
        ]
    )
    meta = META.with_columns(pl.lit(date(2020, 12, 31)).alias("first_day"))
    feats = F.compute_features(
        F.build_grid(daily, date(2022, 1, 2), (date(2021, 1, 1), date(2021, 12, 31))), NODES, meta
    )
    after = feats.filter(pl.col("day") == date(2022, 1, 1)).row(0, named=True)
    assert after["faults_7"] == 0  # неисправность до исключённого года не попадает в окно


def test_node_features_exclude_own_channel():
    daily = _daily([{"channel_id": 1, "day": date(2024, 1, 1), "faults": 3}])
    nodes = pl.DataFrame(
        {"node_id": [10], "day": [date(2024, 1, 1)], "node_faults": [5], "node_power": [0]}
    ).with_columns(pl.col("node_faults", "node_power").cast(pl.Int32))
    feats = F.compute_features(F.build_grid(daily, date(2024, 1, 1)), nodes, META)
    assert feats["node_faults_1"].to_list() == [2]


def test_threshold_respects_precision_target():
    rng = np.random.default_rng(0)
    y = rng.random(5000) < 0.05
    p = np.clip(y * 0.6 + rng.random(5000) * 0.5, 0, 1)
    t = pick_threshold(y, p, np.ones(5000), 0.7)
    pred = p >= t
    assert (pred & y).sum() / pred.sum() >= 0.7


def test_explain_ranks_positive_contributions():
    factors = F.explain({"faults_30": 4, "readings_1": 2}, {"faults_30": 0.8, "readings_1": -0.3, "dow": 0.1})
    assert [f["feature"] for f in factors] == ["faults_30", "dow"]
    assert factors[0]["title"] == "Неисправностей за 30 суток: 4"


def test_health_periodic_only_for_numeric_and_silence_detected():

    from apps.forecasting.health import score_frame

    as_of = datetime(2024, 1, 10, 12, tzinfo=UTC)
    rows = []
    for d in range(1, 11):
        # газ: 48 сообщений в сутки, но 10 января замолчал в 00:00
        last = datetime(2024, 1, d, 23, 30, tzinfo=UTC) if d < 10 else datetime(2024, 1, 10, 0, 0, tzinfo=UTC)
        rows.append(
            {
                "channel_id": 1,
                "day": date(2024, 1, d),
                "readings": 48 if d < 10 else 1,
                "numeric_avg": 0.0,
                "last_ts": last,
            }
        )
        # движение: много сообщений, но дискретный канал — тишина не молчание
        rows.append(
            {
                "channel_id": 2,
                "day": date(2024, 1, d),
                "readings": 100,
                "last_ts": datetime(2024, 1, d, 1, tzinfo=UTC),
            }
        )
    daily = _daily(rows).with_columns(pl.col("last_ts").cast(pl.Datetime("us", "UTC")))
    last_seen = daily.group_by("channel_id").agg(pl.col("last_ts").max().alias("last_seen_at"))
    meta = pl.DataFrame(
        {
            "channel_id": [1, 2],
            "node_id": [10, 10],
            "sensor_type": ["Газовый датчик", "Датчик движения"],
            "value_kind": ["numeric", "state"],
        }
    )
    frame = {r["channel_id"]: r for r in score_frame(daily, last_seen, meta, as_of).iter_rows(named=True)}
    assert frame[1]["periodic"] and frame[1]["silent"] and frame[1]["freshness"] < 1
    assert not frame[2]["periodic"] and not frame[2]["silent"] and frame[2]["completeness"] is None
    assert frame[2]["score"] == 100
