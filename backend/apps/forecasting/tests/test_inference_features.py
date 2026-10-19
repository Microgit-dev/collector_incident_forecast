from datetime import UTC, date, datetime

import polars as pl
import pytest

from apps.forecasting import channel_model as M
from apps.forecasting import data, specs
from apps.forecasting.domain import features as F

from .test_features import _daily


@pytest.fixture
def source(monkeypatch):
    history = _daily(
        [
            {"channel_id": 1, "day": date(2024, 1, 1), "readings": 2},
            {"channel_id": 1, "day": date(2024, 1, 2), "readings": 3, "faults": 1},
            {"channel_id": 2, "day": date(2024, 1, 2), "faults": 2},
        ]
    )
    meta = pl.DataFrame(
        {
            "channel_id": [1, 2],
            "node_id": [10, 10],
            "sensor_type": ["Газовый датчик", "Датчик дыма"],
            "first_day": [date(2024, 1, 1), date(2024, 1, 2)],
        }
    )
    monkeypatch.setattr(data, "load_meta", lambda: meta)
    monkeypatch.setattr(data, "excluded_range", lambda: None)
    monkeypatch.setattr(data, "load_daily", lambda since, until, ids: history)
    monkeypatch.setattr(data, "load_node_daily", lambda since, until: data.node_daily(history, meta))
    monkeypatch.setattr(data, "load_window", lambda end, *, start: history.head(0))
    return history, meta


@pytest.mark.parametrize("spec", [specs.SENSOR_FAILURE, specs.GAS, specs.FLOOD])
def test_midnight_snapshot_matches_training_features(source, monkeypatch, spec):
    history, meta = source
    if spec.task == "flood":
        meta = meta.with_columns(pl.lit("Состояние насоса").alias("sensor_type"))
        monkeypatch.setattr(data, "load_meta", lambda: meta)
    nodes = data.node_daily(history, meta)
    offline = F.compute_features(F.build_grid(history, date(2024, 1, 2)), nodes, meta).filter(
        pl.col("day") == date(2024, 1, 2)
    )
    offline = M._task_meta(offline, spec)
    if spec.uses_weather:
        weather = pl.DataFrame(
            {
                "day": [date(2024, 1, 1), date(2024, 1, 2)],
                "precipitation_mm": [1.0, 2.0],
                "temperature_max_c": [2.0, 3.0],
                "snow_depth_cm": [10.0, 8.0],
            }
        )
        monkeypatch.setattr(data, "load_weather", lambda: weather)
        offline = F.add_weather(offline, weather)
    # 21:00 UTC = начало 3 января по Москве.
    online = M.inference_features(datetime(2024, 1, 2, 21, tzinfo=UTC), spec=spec)
    cols = ["channel_id", *spec.features]
    assert online.select(cols).sort("channel_id").equals(offline.select(cols).sort("channel_id"))


def test_partial_day_does_not_count_yesterday_twice(source, monkeypatch):
    history, _ = source
    window = _daily([{"channel_id": 1, "day": date(2024, 1, 3), "readings": 1}])

    def load_window(end, *, start):
        assert start == datetime(2024, 1, 2, 21, tzinfo=UTC)
        return window

    monkeypatch.setattr(data, "load_window", load_window)
    row = M.inference_features(datetime(2024, 1, 3, 9, tzinfo=UTC), spec=specs.GAS).row(0, named=True)
    assert row["readings_1"] == 1
    assert row["readings_mean_7"] == (history.filter(pl.col("channel_id") == 1)["readings"].sum() + 1) / 7
    assert row["faults_7"] == 1
    # Два сбоя дымового канала: объектные признаки газовой модели используют все типы каналов.
    assert row["node_faults_7"] == 2


def test_silent_current_day_still_advances_calendar(source):
    row = M.inference_features(datetime(2024, 1, 3, 9, tzinfo=UTC), spec=specs.GAS).row(0, named=True)
    assert row["day"] == date(2024, 1, 3)
    assert row["readings_1"] == 0
    assert row["days_since_msg"] == 1
    assert row["last_state"] == "normal"


def test_event_at_midnight_belongs_to_new_day(source, monkeypatch):
    window = _daily([{"channel_id": 1, "day": date(2024, 1, 3), "readings": 1}])
    monkeypatch.setattr(data, "load_window", lambda end, *, start: window)
    row = M.inference_features(datetime(2024, 1, 2, 21, tzinfo=UTC), spec=specs.GAS).row(0, named=True)
    assert row["day"] == date(2024, 1, 3)
    assert row["readings_1"] == 1


def test_current_fault_is_not_treated_as_future_onset(source, monkeypatch):
    window = _daily([{"channel_id": 1, "day": date(2024, 1, 3), "faults": 1, "last_state": "fault"}])
    monkeypatch.setattr(data, "load_window", lambda end, *, start: window)
    frame = M.inference_features(datetime(2024, 1, 3, 9, tzinfo=UTC), spec=specs.SENSOR_FAILURE)
    assert 1 not in frame["channel_id"].to_list()


def test_current_day_weather_is_not_visible_in_intraday_backtest(source, monkeypatch):
    _, meta = source
    monkeypatch.setattr(
        data, "load_meta", lambda: meta.with_columns(pl.lit("Состояние насоса").alias("sensor_type"))
    )
    weather = pl.DataFrame(
        {
            "day": [date(2024, 1, 2), date(2024, 1, 3)],
            "precipitation_mm": [1.0, 999.0],
            "temperature_max_c": [2.0, 999.0],
            "snow_depth_cm": [10.0, 999.0],
        }
    )
    monkeypatch.setattr(data, "load_weather", lambda: weather)
    frame = M.inference_features(datetime(2024, 1, 3, 9, tzinfo=UTC), spec=specs.FLOOD)
    assert frame["day"].unique().to_list() == [date(2024, 1, 3)]
    assert frame["wx_precip_1"].null_count() == frame.height
    assert frame["wx_precip_next"].null_count() == frame.height


def test_data_window_includes_latest_known_event(monkeypatch):
    calls = []

    def query(sql, params):
        calls.append(params)
        assert "ts >= %(start)s AND ts <= %(end)s" in sql
        return pl.DataFrame()

    monkeypatch.setattr(data, "_query", query)
    end = datetime(2024, 1, 3, 9, tzinfo=UTC)
    midnight = datetime(2024, 1, 2, 21, tzinfo=UTC)
    data.load_window(end, start=midnight)
    data.load_window(end)
    assert calls == [
        {"start": midnight, "end": end},
        {"start": datetime(2024, 1, 2, 9, tzinfo=UTC), "end": end},
    ]
