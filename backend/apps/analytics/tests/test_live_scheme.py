from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient

from apps.assets.models import Channel
from apps.forecasting.models import ChannelRisk, Prediction
from apps.incidents import services
from apps.incidents.models import Alert, IncidentType
from apps.telemetry.models import ChannelState


def _channel(node, i, picket):
    return Channel.objects.create(external_id=i, node=node, name=f"Дым ПК{picket}", picket=Decimal(picket))


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_live_stream_counts_signals_episodes_and_queue(tree, make_user):
    user = make_user("disp", "unit_dispatcher", tree["complex"])
    channels = [_channel(tree["house"], i, 10 + i) for i in range(3)]
    for ch in channels:
        services.raise_alert(
            type=IncidentType.FIRE,
            severity="critical",
            node=tree["house"],
            channel=ch,
            title="Пожар",
            source=Alert.Source.RULE,
        )
    body = _client(user).get("/api/v1/analytics/live/", {"minutes": 10}).json()
    assert body["signals"]["total"] == 3 and body["signals"]["by_contour"] == {"physical": 3}
    # три сигнала одного объекта и контура — одна карточка, и она ждёт диспетчера
    assert body["episodes"]["touched"] == 1 and body["action"]["unassigned"] == 1
    assert body["action"]["items"][0]["type"] == "fire"
    assert set(body["risks"]["tasks"]) == {"sensor_failure", "gas", "flood", "fire", "intrusion"}


def test_live_is_limited_to_scope(tree, make_user):
    ch = _channel(tree["house"], 1, 5)
    services.raise_alert(
        type=IncidentType.FIRE,
        severity="high",
        node=tree["house"],
        channel=ch,
        title="x",
        source=Alert.Source.RULE,
    )
    body = _client(make_user("beta", "unit_dispatcher", tree["other"])).get("/api/v1/analytics/live/").json()
    assert body["signals"]["total"] == 0 and body["action"]["open"] == 0


def test_scheme_segments_risk_and_incident_on_picket(tree, make_user):
    near = _channel(tree["house"], 1, 12)
    far = _channel(tree["house"], 2, 300)
    now = timezone.now()
    ChannelRisk.objects.create(
        channel=far, task="sensor_failure", as_of=now, probability=0.8, risk_level="critical"
    )
    ChannelState.objects.create(channel=near, state="fault", changed_at=now, last_seen_at=now)
    services.raise_alert(
        type=IncidentType.FIRE,
        severity="high",
        node=tree["house"],
        channel=near,
        title="x",
        source=Alert.Source.RULE,
    )
    # зона ответственности — шкаф внутри комплекса: строка схемы всё равно по комплексу
    user = make_user("disp", "unit_dispatcher", tree["house"])
    body = _client(user).get("/api/v1/analytics/scheme/").json()
    kinds = {}
    for f in body["features"]:
        kinds.setdefault(f["properties"]["kind"], []).append(f)
    route = kinds["route"][0]["properties"]
    assert route["name"] == "Объект Альфа" and route["picket_from"] == 12 and route["picket_to"] == 300
    assert route["risk_level"] == "critical"
    hot = [s["properties"] for s in kinds["segment"] if s["properties"]["risk_level"] == "critical"]
    assert hot and hot[0]["top"][0]["channel"] == far.pk
    faulty = [s["properties"] for s in kinds["segment"] if s["properties"]["states"]]
    assert faulty == [p for p in faulty if p["states"] == {"fault": 1}] and len(faulty) == 1
    assert kinds["incident"][0]["geometry"]["coordinates"] == [12.0, 0]
    assert kinds["object"][0]["properties"]["name"] == "ДП Альфа"


def test_prediction_card_explains_forecast(tree, make_user):
    ch = _channel(tree["house"], 1, 40)
    now = timezone.now()
    older = Prediction.objects.create(
        task="sensor_failure",
        node=tree["house"],
        channel=ch,
        issued_at=now - timedelta(days=2),
        horizon_hours=24,
        valid_until=now - timedelta(days=1),
        probability=0.5,
        risk_level="high",
        outcome="confirmed",
    )
    p = Prediction.objects.create(
        task="sensor_failure",
        node=tree["house"],
        channel=ch,
        issued_at=now,
        horizon_hours=24,
        valid_until=now + timedelta(days=1),
        probability=0.6,
        risk_level="high",
        factors=[
            {
                "title": "Суток с неисправностями за 90 суток: 12",
                "feature": "x",
                "value": 12,
                "contribution": 1,
            }
        ],
    )
    body = (
        _client(make_user("disp", "unit_dispatcher", tree["complex"]))
        .get(f"/api/v1/forecasting/predictions/{p.pk}/")
        .json()
    )
    assert body["channel_info"]["picket"] == 40.0
    assert body["history"][0]["id"] == older.pk
    assert body["realized"]["live"] == {"confirmed": 1, "resolved": 1, "precision": 1.0}
    assert body["actions"] and body["model_info"]["method"] == "model"
