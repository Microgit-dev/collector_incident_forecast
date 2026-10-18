import json
from datetime import UTC, date, datetime

import numpy as np
import polars as pl
import pytest

from apps.forecasting import channel_model as M
from apps.forecasting.management.commands.benchmark_ml import budget_threshold
from apps.forecasting.offline import ParquetHistory

from .test_features import _daily


@pytest.fixture
def snapshot(tmp_path):
    (tmp_path / "daily").mkdir()
    rows = [{"channel_id": 1, "day": date(2024, 1, d)} for d in range(1, 9)]
    rows[3] |= {"faults": 1, "first_fault_ts": datetime(2024, 1, 4, 9, tzinfo=UTC)}
    frame = _daily(rows).with_columns(pl.lit(None, dtype=pl.Datetime("us")).alias("last_ts"))
    frame.write_parquet(tmp_path / "daily/daily_2024.parquet")
    pl.DataFrame({"channel_id": [1], "node_id": [10], "sensor_type": ["Датчик дыма"]}).write_parquet(
        tmp_path / "channels.parquet"
    )
    (tmp_path / "manifest.json").write_text(json.dumps({"years": {"2024": {}}}))
    return tmp_path


def test_offline_source_preserves_times_and_coverage(snapshot):
    source = ParquetHistory(snapshot)
    assert source.last_complete_day() == date(2024, 1, 8)
    assert source.load_meta()["first_day"].to_list() == [date(2024, 1, 1)]
    frame = source.load_daily(date(2024, 1, 3), date(2024, 1, 5), [1])
    assert frame["day"].to_list() == [date(2024, 1, 3), date(2024, 1, 4)]
    assert frame["first_fault_ts"].dtype == pl.Datetime("us", "UTC")
    assert source.load_node_daily()["node_faults"].sum() == 1
    assert source.load_weather().is_empty()


def test_offline_source_builds_same_labels_without_database(snapshot, settings):
    settings.ARTIFACTS_DIR = snapshot / "artifacts"
    source = ParquetHistory(snapshot)
    frame, _, _ = M.build_dataset(source=source, neg_rate=1.0)
    positive = frame.filter(pl.col("y"))
    assert positive["day"].to_list() == [date(2024, 1, 3)]
    assert frame["day"].max() == date(2024, 1, 7)
    assert frame.equals(M.build_dataset(source=source, neg_rate=1.0)[0])
    first_key = source.cache_key
    (snapshot / "manifest.json").write_text(json.dumps({"years": {"2024": {}}, "revision": 2}))
    assert ParquetHistory(snapshot).cache_key != first_key


def test_validation_budget_does_not_split_ties():
    scores = np.array([0.9] * 5 + [0.8] * 10 + [0.1] * 100)
    assert (scores >= budget_threshold(scores, 3)).sum() == 0
    assert (scores >= budget_threshold(scores, 10)).sum() == 5
    assert (scores >= budget_threshold(scores, 15)).sum() == 15
