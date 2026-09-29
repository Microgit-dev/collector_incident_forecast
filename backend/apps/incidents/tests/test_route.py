from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.assets.models import Channel, SensorType
from apps.incidents import rules
from apps.incidents.domain.correlation import PHYSICAL, contour
from apps.incidents.models import Incident, IncidentType
from apps.incidents.route import intrusion_route
from apps.normalization.domain.engine import State
from apps.topology.models import Node

BUILDING = {
    "type": "Polygon",
    "coordinates": [
        [[37.6040, 55.7040], [37.6050, 55.7040], [37.6050, 55.7045], [37.6040, 55.7045], [37.6040, 55.7040]]
    ],
}


def _change(channel, state, ts, numeric=None):
    return SimpleNamespace(
        channel_id=channel.pk, ts=ts, current=state, previous=State.NORMAL, facet="primary", numeric=numeric
    )


@pytest.fixture
def guarded(tree):
    Node.objects.filter(pk=tree["complex"].pk).update(geometry=BUILDING)
    sensor = SensorType.objects.create(
        name="Датчик движения", system_type="Охранная подсистема", domain="intrusion"
    )
    hatch = Channel.objects.create(
        external_id=1,
        node=tree["house"],
        sensor_type=sensor,
        name="Люк ПК10",
        picket=10,
        location=[37.6041, 55.7042],
    )
    door = Channel.objects.create(
        external_id=2, node=tree["house"], sensor_type=sensor, name="Дверь ПК12", picket=12
    )
    motion = Channel.objects.create(
        external_id=3, node=tree["house"], sensor_type=sensor, name="ОД ПК15", picket=15
    )
    return {
        "hatch": hatch,
        "door": door,
        "motion": motion,
        "house": tree["house"],
        "complex": tree["complex"],
    }


def test_abnormal_temperature_is_its_own_accident(tree):
    sensor = SensorType.objects.create(name="Датчик температуры", domain="climate")
    channel = Channel.objects.create(
        external_id=9, node=tree["house"], sensor_type=sensor, name="Темп. ВШ ПК88"
    )
    rules.on_states_changed(None, changes=[_change(channel, State.ALARM, timezone.now(), numeric=61.5)])
    incident = Incident.objects.get()
    assert incident.type == IncidentType.TEMPERATURE and incident.severity == "high"
    assert contour(incident.type) == PHYSICAL
    # один канал — «ложное срабатывание» впереди, но гипотеза аварии с показанием есть
    real = next(h for h in incident.hypotheses if h["code"] == "temperature")
    assert any("61.5" in e for e in real["evidence"])


def test_intruder_route_follows_triggers_in_time(guarded):
    t0 = timezone.now()
    seq = [("hatch", 0), ("door", 20), ("motion", 40), ("motion", 45), ("motion", 50)]
    rules.on_states_changed(
        None, changes=[_change(guarded[name], State.ALARM, t0 + timedelta(seconds=s)) for name, s in seq]
    )
    incident = Incident.objects.get()
    assert incident.type == IncidentType.INTRUSION
    route = intrusion_route(incident)
    # три шага: подряд идущие сработки одного датчика склеены
    assert [s["name"] for s in route["steps"]] == ["Люк ПК10", "Дверь ПК12", "ОД ПК15"]
    assert route["steps"][2]["count"] == 3 and route["duration_s"] == 50
    # люк стоит своей точкой, остальные — на контуре объекта по пикету
    assert route["steps"][0]["position"] == [37.6041, 55.7042] and route["steps"][0]["placed"]
    assert all(route["steps"][i]["position"] for i in (1, 2)) and not route["steps"][1]["placed"]
    assert route["line"]["type"] == "LineString" and len(route["line"]["coordinates"]) == 3
    assert route["distance_m"] > 0 and "увеличения" in route["heading"]
    assert route["object"] == guarded["complex"].pk and route["geometry"] == BUILDING


def test_route_only_for_intrusion_and_in_incident_card(guarded, make_user):
    rules.on_states_changed(None, changes=[_change(guarded["hatch"], State.ALARM, timezone.now())])
    incident = Incident.objects.get()
    user = make_user("disp", "ods_dispatcher", guarded["complex"].get_parent())
    client = APIClient()
    client.force_authenticate(user)
    card = client.get(f"/api/v1/incidents/items/{incident.pk}/").data
    assert card["route"]["steps"][0]["name"] == "Люк ПК10" and card["route"]["line"] is None

    Incident.objects.filter(pk=incident.pk).update(type=IncidentType.FIRE)
    assert client.get(f"/api/v1/incidents/items/{incident.pk}/").data["route"] is None
