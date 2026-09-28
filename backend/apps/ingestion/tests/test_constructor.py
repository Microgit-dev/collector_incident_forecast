"""Конструктор источников: шаблоны формата, песочница с нормализацией, приём по ключу, обёртка в Kafka."""

import pytest
from rest_framework.test import APIClient

from apps.assets.models import Channel, SensorType
from apps.ingestion import constructor
from apps.ingestion.models import DataSource
from apps.ingestion.templates import LIBRARY, parse, resolve
from apps.normalization.models import SensorProfile


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.parametrize("template", LIBRARY, ids=[t["code"] for t in LIBRARY])
def test_library_samples_parse(template):
    result = parse(template["format"], template["config"], template["sample"])
    assert result.events and not result.errors


def test_resolve_paths():
    doc = {"a": {"b": [{"c": 1}, {"c": 2}]}, "^": {"time": 5}}
    assert resolve(doc, "a.b[1].c") == 2
    assert resolve(doc, "$.a.b[0].c") == 1
    assert resolve(doc, "^.time") == 5
    assert resolve(doc, "=80000001") == "80000001"
    assert resolve(doc, "a.x") is None


def test_parse_errors_do_not_stop_batch():
    config = {"fields": {"channel": "id", "ts": "t", "ts_format": "epoch_s", "value": "v"}}
    text = '{"id": 1, "t": 1782292500, "v": 5}\n{"id": "abc", "t": 1782292500, "v": 6}\n{"id": 3, "t": 1782292500}'
    result = parse("json", config, text)
    assert [e.channel_external_id for e in result.events] == [1]
    assert {e["item"] for e in result.errors} == {2, 3}
    # одинаковое событие даёт тот же ид — повторная доставка не дублирует показание
    again = parse("json", config, '{"id": 1, "t": 1782292500, "v": 5}')
    assert again.events[0].event_id == result.events[0].event_id


def test_preview_normalizes_with_channel_profile(db, tree):
    profile = SensorProfile.objects.create(
        code="ch4", name="Метан", value_kind="numeric", valid_min=0, valid_max=5, alarm_threshold=1, unit="%"
    )
    stype = SensorType.objects.create(name="Газовый датчик", domain="gas", profile=profile)
    Channel.objects.create(external_id=80000003, node=tree["house"], name="Метан ПК5", sensor_type=stype)
    gateway = next(t for t in LIBRARY if t["code"] == "gateway-multi")
    sample = gateway["sample"].replace('"v": 0.02', '"v": 1.4')
    result = constructor.preview("json", gateway["config"], sample)
    rows = {r["channel"]: r for r in result["events"]}
    assert rows[80000003]["known"] and rows[80000003]["state"] == "alarm" and rows[80000003]["numeric"] == 1.4
    assert rows[80000001]["known"] is False  # канал ещё не заведён — показано, как его нормализует профиль


def test_constructor_api_and_rights(tree, make_user):
    analyst = make_user("analyst", "analyst", tree["district"])
    client = _client(analyst)
    assert len(client.get("/api/v1/ingestion/templates/library/").json()) == len(LIBRARY)
    text_line = next(t for t in LIBRARY if t["code"] == "text-line")
    created = client.post(
        "/api/v1/ingestion/templates/",
        {
            "code": "ctl-17",
            "name": "Контроллер 17",
            "format": "regex",
            "config": text_line["config"],
            "sample": text_line["sample"],
        },
        format="json",
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["token"] and body["ingest_url"] == "/api/v1/ingestion/templates/ctl-17/events/"
    preview = client.post(
        "/api/v1/ingestion/templates/preview/",
        {"format": "regex", "config": text_line["config"], "sample": text_line["sample"]},
        format="json",
    ).json()
    assert preview["total"] == 2
    disp = make_user("disp", "unit_dispatcher", tree["district"])
    assert _client(disp).post("/api/v1/ingestion/templates/", {"code": "x"}, format="json").status_code == 403


def test_ingest_by_token(tree, make_user, monkeypatch):
    sent = []
    monkeypatch.setattr(constructor, "publish", lambda events: sent.extend(events) or len(events))
    template = next(t for t in LIBRARY if t["code"] == "mqtt-kv")
    source = DataSource.objects.create(
        code="mqtt-1",
        name="MQTT",
        kind="stream",
        adapter="template",
        format="regex",
        config=template["config"],
        token="secret",
    )
    anon = APIClient()
    url = f"/api/v1/ingestion/templates/{source.code}/events/"
    assert anon.post(url, "T=21.3;H=45", content_type="text/plain").status_code == 401
    wrong = anon.post(url, "T=21.3;H=45", content_type="text/plain", HTTP_AUTHORIZATION="Token nope")
    assert wrong.status_code == 401
    ok = anon.post(url, "T=21.3;H=45", content_type="text/plain", HTTP_AUTHORIZATION="Token secret")
    assert ok.status_code == 202 and ok.json()["accepted"] == 2
    assert [e.channel_external_id for e in sent] == [80000001, 80000002]
    assert sent[0].source == "mqtt-1"


def test_consumer_unwraps_template_messages(db):
    template = next(t for t in LIBRARY if t["code"] == "mqtt-kv")
    DataSource.objects.create(
        code="mqtt-1",
        name="MQTT",
        kind="stream",
        adapter="template",
        format="regex",
        config=template["config"],
    )
    cache = constructor.TemplateCache()
    events = constructor.unwrap({"template": "mqtt-1", "payload": "T=5;H=50"}, cache)
    assert [e.raw_value for e in events] == ["5", "50"]
    plain = constructor.unwrap(
        {"event_id": 1, "channel_external_id": 7, "ts": "2026-06-24T12:00:00+03:00", "raw_value": "1"}, cache
    )
    assert plain[0].channel_external_id == 7
    with pytest.raises(ValueError):
        constructor.unwrap({"template": "missing", "payload": "x"}, cache)
