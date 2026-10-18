from datetime import UTC, date, datetime

import polars as pl
import pytest

from apps.forecasting.short_windows import aggregate_windows, attach_windows
from apps.ingestion.archive import _daily_month


def events():
    # UTC -> Moscow: 17:59, 18:00, 22:59, 23:00, 23:59, next midnight.
    times = [(14, 59), (15, 0), (19, 59), (20, 0), (20, 59), (21, 0)]
    return pl.DataFrame(
        {
            "channel_id": [1] * 6,
            "ts": [datetime(2024, 1, 1, h, m, tzinfo=UTC) for h, m in times],
            "state": ["normal", "warning", "normal", "fault", "alarm", "alarm"],
            "quality": ["ok", "ok", "drift", "sentinel", "ok", "ok"],
            "numeric": [0.1, 0.2, 0.3, 9999.0, 0.5, 100.0],
            "facet": ["primary"] * 6,
        }
    )


def test_windows_use_moscow_boundaries_and_ignore_invalid_numeric():
    result = aggregate_windows(events().lazy()).collect().filter(pl.col("day") == date(2024, 1, 1))
    row = result.row(0, named=True)
    assert row["short_readings_1h"] == 2
    assert row["short_readings_6h"] == 4
    assert row["control_readings_24h"] == 5
    assert row["short_faults_1h"] == 1
    assert row["short_num_avg_1h"] == 0.5  # sentinel excluded, target-day 100 excluded
    assert row["short_num_avg_6h"] == pytest.approx(1 / 3)
    assert row["short_staleness_hours"] == pytest.approx(1 / 60)


def test_changing_target_day_cannot_change_features_before_prediction():
    raw = events()
    before = aggregate_windows(raw.lazy()).collect().filter(pl.col("day") == date(2024, 1, 1))
    future = raw.tail(1).with_columns(pl.lit(-500.0).alias("numeric"), pl.lit("fault").alias("state"))
    after = (
        aggregate_windows(pl.concat([raw.head(5), future]).lazy())
        .collect()
        .filter(pl.col("day") == date(2024, 1, 1))
    )
    assert before.equals(after)


def test_24h_controls_match_existing_daily_aggregation():
    raw = events().lazy()
    short = aggregate_windows(raw).collect().sort("day")
    daily = _daily_month(raw).sort("day")
    assert short["control_readings_24h"].equals(daily["readings"])
    assert short["control_faults_24h"].equals(daily["faults"])
    assert short["control_numeric_avg_24h"].to_list() == pytest.approx(daily["numeric_avg"].to_list())


def test_join_preserves_labels_order_and_missing_windows():
    frame = pl.DataFrame(
        {
            "channel_id": [2, 1],
            "day": [date(2024, 1, 1)] * 2,
            "y": [True, False],
            "readings_1": [0, 5],
        }
    )
    result = attach_windows(frame, aggregate_windows(events().lazy()).collect())
    assert result.select(frame.columns).equals(frame)
    assert result["short_readings_1h"].to_list() == [0, 2]
    assert result["short_num_avg_1h"].to_list() == [None, 0.5]
    assert result["short_staleness_hours"][0] is None
    with pytest.raises(ValueError, match="24-hour control"):
        attach_windows(
            frame.with_columns(pl.lit(10).alias("readings_1")), aggregate_windows(events().lazy()).collect()
        )
