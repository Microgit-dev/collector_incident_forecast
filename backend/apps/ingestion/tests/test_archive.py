import polars as pl
import pytest

from apps.assets.models import Channel, SensorType
from apps.ingestion.archive import daily_frame, normalize_journal
from apps.normalization.models import SensorProfile
from apps.normalization.services import seed_default_taxonomy

JOURNAL = """ид_события,ид_канала_данных,дата,время,тревожное,значение_датчика
1,100,2019-03-01,10:00:00,f,0.02
2,100,2019-03-01,10:01:00,f,1.20
3,100,2019-03-01,10:02:00,f,-127
3,100,2019-03-01,10:02:00,f,-127
4,200,2019-03-01,10:03:00,f,Обнаружено движение
5,200,2019-03-01,10:04:00,t,Обнаружено движение
6,200,2019-03-01,10:05:00,f,01.01.1970 03:00:00
7,200,2019-03-01,не время,f,Норма
8,200,2020-01-05,10:00:00,f,Норма
9,999,2019-03-02,11:00:00,f,Неисправен
1,200,2019-04-10,09:00:00,f,Норма
"""


@pytest.fixture
def channels(tree):
    seed_default_taxonomy()
    gas = SensorType.objects.create(
        name="Газовый датчик", domain="gas", profile=SensorProfile.objects.get(code="gas_methane")
    )
    motion = SensorType.objects.create(
        name="Датчик движения", domain="intrusion", profile=SensorProfile.objects.get(code="discrete")
    )
    Channel.objects.create(external_id=100, node=tree["house"], sensor_type=gas, name="ГАЗ ПК1")
    Channel.objects.create(external_id=200, node=tree["house"], sensor_type=motion, name="ОД ПК2")


def test_normalize_journal_report_and_parquet(tmp_path, channels):
    src = tmp_path / "ext-journal-2019.csv"
    src.write_text(JOURNAL, encoding="utf-8")
    dst = tmp_path / "journal_2019.parquet"

    report = normalize_journal(src, dst, year=2019)

    assert report["rows_total"] == 11
    assert report["duplicates"] == 1
    assert report["bad_time"] == 1
    assert report["out_of_period"] == 1  # 2020 в файле за 2019
    # id 1 переиспользован другим каналом в другом месяце — это отдельное событие, не дубль
    assert report["rows_loaded"] == 8
    assert report["unknown_channels"] == 1 and report["unknown_channel_rows"] == 1
    assert Channel.objects.get(external_id=999).in_catalog is False

    frame = (
        pl.read_parquet(dst)
        .filter(pl.col("channel_ext") != 200)
        .vstack(pl.read_parquet(dst).filter((pl.col("channel_ext") == 200) & (pl.col("event_id") != 1)))
        .sort("event_id")
    )
    states = dict(zip(frame["event_id"].to_list(), frame["state"].to_list(), strict=True))
    assert states == {1: "normal", 2: "alarm", 3: "fault", 4: "event", 5: "alarm", 6: "fault", 9: "fault"}
    assert report["by_quality"] == {"ok": 6, "sentinel": 1, "epoch_artifact": 1}

    daily = daily_frame(pl.scan_parquet(dst))
    gas = daily.filter(pl.col("channel_id") == Channel.objects.get(external_id=100).pk).row(0, named=True)
    # Служебный код -127 не попадает в числовую статистику концентрации
    assert (gas["readings"], gas["faults"], gas["numeric_min"], gas["numeric_max"]) == (3, 1, 0.02, 1.2)
