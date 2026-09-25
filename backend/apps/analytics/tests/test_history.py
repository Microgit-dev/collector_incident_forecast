from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import polars as pl
import pytest
from rest_framework.test import APIClient

from apps.analytics.history import SCHEMA, channel_history, node_history, period
from apps.assets.models import Channel
from apps.incidents import services as incidents
from apps.incidents.models import Alert, DecisionCause, DecisionOutcome, IncidentType
from apps.telemetry.models import ChannelDaily, Reading


@pytest.fixture
def archive(settings, tmp_path):
    settings.ARTIFACTS_DIR = tmp_path
    (tmp_path / "archive").mkdir()
    return tmp_path / "archive"


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _write(archive, year, channel_id, rows):
    frame = pl.DataFrame(
        [
            {
                **dict(zip(SCHEMA, r, strict=True)),
                "event_id": i,
                "channel_ext": 1,
                "channel_id": channel_id,
                "raw_alarm": False,
            }
            for i, r in enumerate(rows)
        ],
        schema={
            **SCHEMA,
            "event_id": pl.Int64,
            "channel_ext": pl.Int64,
            "channel_id": pl.Int64,
            "raw_alarm": pl.Boolean,
        },
    )
    frame.write_parquet(archive / f"journal_{year}.parquet")


@pytest.fixture
def gas(tree):
    return Channel.objects.create(external_id=1, node=tree["house"], name="ГАЗ Д1 ПК12", picket=Decimal(12))


def test_raw_period_joins_archive_and_operational(gas, archive, tree):
    t0 = datetime(2024, 3, 1, 9, tzinfo=UTC)
    _write(
        archive,
        2024,
        gas.pk,
        [
            (t0, "normal", "0.01", 0.01, "primary", "ok"),
            (t0 + timedelta(hours=1), "alarm", "1.30", 1.3, "primary", "ok"),
            (t0 + timedelta(hours=2), "fault", "-100", -100.0, "primary", "sentinel"),
            (t0 + timedelta(hours=3), "normal", "0.02", 0.02, "primary", "ok"),
        ],
    )
    # оперативный контур начинается позже архива
    Reading.objects.create(
        ts=datetime(2024, 3, 2, 12, tzinfo=UTC),
        event_id=1,
        channel=gas,
        raw_value="0.05",
        numeric=0.05,
        state="normal",
    )
    start, end = period(date(2024, 3, 1), date(2024, 3, 2))
    h = channel_history(gas, start, end)
    assert h["resolution"] == "raw" and h["sources"] == ["архив 2024", "оперативный контур"]
    assert [p["v"] for p in h["numeric"]] == [
        0.01,
        1.3,
        0.02,
        0.05,
    ]  # служебный код не рисуется как концентрация
    assert h["invalid"][0]["quality"] == "sentinel" and h["invalid_total"] == 1
    states = [i["state"] for i in h["states"]["primary"]]
    assert states == ["normal", "alarm", "fault", "normal"]
    assert h["states"]["primary"][-1]["to"] == end


def test_long_raw_series_is_bucketed(gas, archive):
    t0 = datetime(2024, 5, 1, tzinfo=UTC)
    _write(
        archive,
        2024,
        gas.pk,
        [
            (t0 + timedelta(minutes=i), "normal", "0.01", 0.01 + (i % 7) / 100, "primary", "ok")
            for i in range(8000)
        ],
    )
    h = channel_history(gas, *period(date(2024, 5, 1), date(2024, 5, 7)))
    assert h["resolution"] == "bucket" and h["bucket_s"] in (900, 1800)
    assert 100 < len(h["numeric"]) <= 600
    assert all(p["min"] <= p["v"] <= p["max"] for p in h["numeric"])


def test_long_period_uses_daily_showcase(gas, archive):
    for d in range(60):
        day = date(2024, 1, 1) + timedelta(days=d)
        ChannelDaily.objects.create(
            day=day,
            channel=gas,
            readings=100,
            normal=99,
            alarms=1 if d == 10 else 0,
            numeric_avg=0.01,
            first_ts=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=d),
            last_ts=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=d, hours=23),
        )
    h = channel_history(gas, *period(date(2024, 1, 1), date(2024, 2, 29)))
    assert h["resolution"] == "daily" and len(h["daily"]) == 60 and h["numeric"] == []
    assert h["daily"][10]["alarms"] == 1


def test_incidents_and_decisions_overlay(gas, archive, make_user, tree):
    disp = make_user("disp", "unit_dispatcher", tree["complex"])
    incident = incidents.raise_alert(
        type=IncidentType.GAS,
        severity="high",
        node=tree["house"],
        channel=gas,
        title="Газ",
        source=Alert.Source.RULE,
    ).incident
    incidents.decide(incident, disp, outcome=DecisionOutcome.FALSE_ALARM, cause=DecisionCause.SENSOR_FAULT)
    today = incident.opened_at.date()
    h = channel_history(gas, *period(today - timedelta(days=1), today + timedelta(days=1)))
    item = h["incidents"][0]
    assert item["id"] == incident.pk and item["decision"]["cause"] == "Неисправность датчика"


def test_node_matrix_worst_state_per_day(gas, tree):
    quiet = Channel.objects.create(external_id=2, node=tree["house"], name="ДД ПК20")
    Channel.objects.create(external_id=3, node=tree["house"], name="молчит")
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    for day, faults, alarms in ((date(2024, 1, 1), 2, 1), (date(2024, 1, 2), 3, 0)):
        ChannelDaily.objects.create(
            day=day, channel=gas, readings=10, faults=faults, alarms=alarms, first_ts=ts, last_ts=ts
        )
    ChannelDaily.objects.create(
        day=date(2024, 1, 1), channel=quiet, readings=5, normal=5, first_ts=ts, last_ts=ts
    )
    h = node_history(tree["complex"], *period(date(2024, 1, 1), date(2024, 1, 2)))
    assert h["days"] == ["2024-01-01", "2024-01-02"]
    assert h["rows"][0]["name"] == "ГАЗ Д1 ПК12"  # сначала каналы с проблемами
    assert h["rows"][0]["cells"] == {"2024-01-01": "alarm", "2024-01-02": "fault"}
    assert h["silent"] == 1 and h["totals"][0]["reporting"] == 2


def test_api_scope_and_permissions(gas, archive, tree, make_user):
    own = make_user("disp", "unit_dispatcher", tree["complex"])
    foreign = make_user("beta", "unit_dispatcher", tree["other"])
    tech = make_user("tech", "technician", tree["complex"])
    q = {"channel": gas.pk, "from": "2024-03-01", "to": "2024-03-02"}
    assert _client(own).get("/api/v1/history/channel/", q).status_code == 200
    assert _client(foreign).get("/api/v1/history/channel/", q).status_code == 404
    assert _client(tech).get("/api/v1/history/channel/", q).status_code == 403
    assert _client(own).get("/api/v1/history/channel/", {**q, "to": "2020-01-01"}).status_code == 400
    node = _client(own).get(
        "/api/v1/history/node/", {"node": tree["complex"].pk, "from": "2024-01-01", "to": "2024-01-31"}
    )
    assert node.status_code == 200 and node.json()["node"]["channels"] == 1
    assert _client(own).get("/api/v1/history/coverage/").json()["max_raw_days"] == 31


def test_channels_within_subtree(gas, tree, make_user):
    body = _client(make_user("disp", "unit_dispatcher", tree["complex"])).get(
        "/api/v1/assets/channels/", {"within": tree["complex"].pk}
    )
    assert [c["id"] for c in body.json()["results"]] == [gas.pk]
