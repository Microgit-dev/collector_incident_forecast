from datetime import date, timedelta

import polars as pl
import pytest

from apps.forecasting import channel_model as M
from apps.forecasting.temporal_validation import TemporalFold, TemporalHistory

from .test_offline import snapshot  # noqa: F401
from .test_validation import _rows


@pytest.mark.parametrize("year", [2023, 2024, 2025])
@pytest.mark.parametrize("horizon", [1, 7])
def test_fold_keeps_whole_target_window_in_its_period(year, horizon):
    fold = TemporalFold(year)
    start = date(year - 1, 12, 1)
    frame = _rows([start + timedelta(days=i) for i in range(430)])
    parts = fold.split(frame, horizon)
    assert parts["train"]["day"].max() + timedelta(days=horizon) < fold.valid_from
    assert parts["valid"]["day"].min() == fold.valid_from
    assert parts["valid"]["day"].max() + timedelta(days=horizon) < fold.test_from
    assert parts["test"]["day"].min() == fold.test_from
    assert parts["test"]["day"].max() + timedelta(days=horizon) < fold.end


def test_sampling_boundary_moves_with_fold_and_retains_early_holdouts():
    start = date(2022, 1, 1)
    frame = _rows([start + timedelta(days=i) for i in range(1095)])
    sampled = M._sample_rows(frame, 0.05, train_before=date(2023, 1, 1))
    assert sampled.filter(pl.col("day") >= date(2023, 1, 1)).height == 730
    assert sampled.filter(pl.col("day") >= date(2023, 1, 1))["weight"].unique().to_list() == [1.0]
    assert 5 < sampled.filter(pl.col("day") < date(2023, 1, 1)).height < 40


def test_restricted_source_hides_future_from_every_aggregate(snapshot):  # noqa: F811
    source = TemporalHistory(snapshot, date(2024, 1, 3))
    assert source.last_daily_day() == date(2024, 1, 3)
    assert source.last_complete_day() is None  # three-day fixture is shorter than continuity policy
    assert source.load_daily(date(2024, 1, 1), date(2025, 1, 1))["day"].max() == date(2024, 1, 3)
    assert source.load_node_daily()["node_faults"].sum() == 0  # fault is on Jan 4
    assert source.load_node_daily()["day"].max() == date(2024, 1, 3)
    assert source.load_meta()["first_day"].min() == date(2024, 1, 1)
    assert source.cache_key != TemporalHistory(snapshot, date(2024, 1, 4)).cache_key


def test_sampling_cache_does_not_mix_temporal_protocols(snapshot, settings):  # noqa: F811
    settings.ARTIFACTS_DIR = snapshot / "models_cache"
    source = TemporalHistory(snapshot, date(2024, 1, 8))
    first, _, _ = M.build_dataset(source=source, neg_rate=0.01, train_before=date(2024, 1, 1))
    assert first.height == 7  # the fixture keeps last_state normal even on the day with a fault message
    assert first["weight"].unique().to_list() == [1.0]
    M.build_dataset(source=source, neg_rate=0.01, train_before=date(2024, 1, 5))
    assert len(list((settings.ARTIFACTS_DIR / "models").glob("*.parquet"))) == 2
    assert first.equals(M.build_dataset(source=source, neg_rate=0.01, train_before=date(2024, 1, 1))[0])
