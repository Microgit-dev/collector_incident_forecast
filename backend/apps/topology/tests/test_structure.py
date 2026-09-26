from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Secondment
from apps.assets.models import Channel
from apps.incidents import services as incidents
from apps.incidents.models import Alert, IncidentType
from apps.notifications.models import Notification
from apps.topology import geo, structure
from apps.topology.models import Node, NodeKind

SQUARE = {
    "type": "Polygon",
    "coordinates": [[[37.60, 55.70], [37.61, 55.70], [37.61, 55.71], [37.60, 55.71], [37.60, 55.70]]],
}
NEXT = {
    "type": "Polygon",
    "coordinates": [[[37.61, 55.70], [37.62, 55.70], [37.62, 55.71], [37.61, 55.71], [37.61, 55.70]]],
}
FAR = {
    "type": "Polygon",
    "coordinates": [[[37.70, 55.70], [37.71, 55.70], [37.71, 55.71], [37.70, 55.71], [37.70, 55.70]]],
}
BUILDING = {
    "type": "Polygon",
    "coordinates": [
        [[37.6040, 55.7040], [37.6050, 55.7040], [37.6050, 55.7045], [37.6040, 55.7045], [37.6040, 55.7040]]
    ],
}


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def world(tree, make_user):
    head = make_user("head", "head", tree["district"])
    north = structure.create_zone(head, name="Северная", geometry=SQUARE)
    south = structure.create_zone(head, name="Южная", geometry=NEXT)
    east = structure.create_zone(head, name="Восточная", geometry=FAR)
    structure.move_object(head, tree["complex"], north.pk)
    structure.move_object(head, tree["other"], east.pk)
    return {
        "head": head,
        "north": Node.objects.get(pk=north.pk),
        "south": Node.objects.get(pk=south.pk),
        "east": Node.objects.get(pk=east.pk),
        "alpha": Node.objects.get(pk=tree["complex"].pk),
        "beta": Node.objects.get(pk=tree["other"].pk),
        "house": Node.objects.get(pk=tree["house"].pk),
    }


def test_zones_adjacency_and_moving_objects(world):
    north, south, east = world["north"], world["south"], world["east"]
    assert north.kind == NodeKind.ZONE and north.depth == 2
    # касающиеся контуры — смежные, дальний — нет
    assert set(north.adjacent.values_list("pk", flat=True)) == {south.pk}
    assert not east.adjacent.exists()
    # объект переехал со своими частями: часть объекта теперь в поддереве зоны
    assert world["alpha"].path.startswith(north.path) and world["house"].path.startswith(world["alpha"].path)


def test_dispatcher_assigned_to_zone_sees_its_objects(world, make_user):
    disp = make_user("disp", "unit_dispatcher", world["north"])
    incident = incidents.raise_alert(
        type=IncidentType.FIRE, severity="high", node=world["house"], title="Дым", source=Alert.Source.RULE
    ).incident
    other = incidents.raise_alert(
        type=IncidentType.FIRE, severity="high", node=world["beta"], title="Дым", source=Alert.Source.RULE
    ).incident
    client = _client(disp)
    assert client.get(f"/api/v1/incidents/items/{incident.pk}/").status_code == 200
    assert client.get(f"/api/v1/incidents/items/{other.pk}/").status_code == 404


def test_only_managers_create_zones_and_objects(world, make_user):
    disp = make_user("disp", "unit_dispatcher", world["north"])
    assert _client(disp).post("/api/v1/topology/zones/", {"name": "Х"}, format="json").status_code == 400
    body = {"zone": world["north"].pk, "name": "Насосная", "geometry": BUILDING}
    assert _client(disp).post("/api/v1/topology/objects/", body, format="json").status_code == 400
    analyst = make_user("analyst", "analyst", world["north"])
    created = _client(analyst).post("/api/v1/topology/objects/", body, format="json")
    assert created.status_code == 201, created.content
    obj = Node.objects.get(pk=created.json()["id"])
    assert obj.kind == NodeKind.COMPLEX and obj.path.startswith(world["north"].path)
    # аналитик не создаёт зоны — это руководитель
    assert _client(analyst).post("/api/v1/topology/zones/", {"name": "Х"}, format="json").status_code == 400


def test_manual_sensor_gets_its_own_id_and_can_be_attached(world):
    head = world["head"]
    response = _client(head).post(
        "/api/v1/topology/sensors/",
        {"node": world["alpha"].pk, "name": "Газ ПК5", "location": [37.6045, 55.7042]},
        format="json",
    )
    assert response.status_code == 201
    channel = Channel.objects.get(pk=response.json()["id"])
    assert channel.external_id > structure.MANUAL_CHANNEL_BASE and not channel.in_catalog
    moved = _client(head).patch(
        f"/api/v1/topology/sensors/{channel.pk}/", {"node": world["north"].pk}, format="json"
    )
    assert moved.status_code == 200 and moved.json()["node"] == world["north"].pk


def test_secondment_rules_visibility_and_escalation(world, make_user):
    head = world["head"]
    petrov = make_user("petrov", "unit_dispatcher", world["south"])
    beta_card = incidents.raise_alert(
        type=IncidentType.GAS, severity="high", node=world["beta"], title="Метан", source=Alert.Source.RULE
    ).incident
    url = f"/api/v1/topology/staff/{petrov.pk}/second/"
    # Восточная не смежна с Южной — только крайний случай с причиной
    denied = _client(head).post(url, {"zone": world["east"].pk, "hours": 4}, format="json")
    assert denied.status_code == 400 and "крайний случай" in denied.json()["detail"]
    no_reason = _client(head).post(url, {"zone": world["east"].pk, "emergency": True}, format="json")
    assert no_reason.status_code == 400
    assert _client(petrov).get(f"/api/v1/incidents/items/{beta_card.pk}/").status_code == 404
    ok = _client(head).post(
        url, {"zone": world["east"].pk, "hours": 4, "emergency": True, "reason": "авария"}, format="json"
    )
    assert ok.status_code == 201 and ok.json()["emergency"] is True
    assert Notification.objects.filter(user=petrov, title__contains="Восточная").exists()
    # командированный видит карточки зоны и получает её эскалации
    assert _client(petrov).get(f"/api/v1/incidents/items/{beta_card.pk}/").status_code == 200
    assert petrov in incidents._users_with_scope(world["east"])
    # в смежную — без крайнего случая
    north = _client(head).post(url, {"zone": world["north"].pk, "hours": 2}, format="json")
    assert north.status_code == 201 and north.json()["emergency"] is False
    # отзыв и истечение срока закрывают доступ
    _client(head).post(f"/api/v1/topology/secondments/{ok.json()['id']}/recall/")
    assert _client(petrov).get(f"/api/v1/incidents/items/{beta_card.pk}/").status_code == 404
    Secondment.objects.update(ends_at=timezone.now() - timedelta(minutes=1))
    assert petrov not in incidents._users_with_scope(world["north"])


def test_monitoring_map_accent_on_own_zone(world, make_user):
    disp = make_user("disp", "unit_dispatcher", world["north"])
    world["alpha"].geometry = BUILDING
    world["alpha"].save()
    incidents.raise_alert(
        type=IncidentType.FIRE,
        severity="critical",
        node=world["house"],
        title="Дым",
        source=Alert.Source.RULE,
    )
    data = _client(disp).get("/api/v1/analytics/monitoring/").json()
    objects = {o["name"]: o for o in data["objects"]}
    alpha, beta = objects["Объект Альфа"], objects["Объект Бета"]
    assert alpha["mine"] and alpha["incidents"] == 1 and alpha["incident_level"] == "critical"
    assert not beta["mine"] and "incidents" not in beta  # чужой объект без подробностей
    zones = {z["name"]: z for z in data["zones"]}
    assert zones["Северная"]["home"] and zones["Южная"]["adjacent"] and not zones["Восточная"]["mine"]
    assert data["mode"] == "situation" and "situation" in data["modes"]
    assert data["bbox"] is not None
    others = _client(disp).get("/api/v1/analytics/monitoring/others/").json()
    assert [r["name"] for r in others["results"]] == ["Объект Бета"]
    detail = _client(disp).get(f"/api/v1/analytics/monitoring/objects/{world['beta'].pk}/").json()
    assert detail["mine"] is False and "sensors" not in detail


def test_monitoring_for_brigade_shows_orders_not_incidents(world, make_user):
    tech = make_user("tech", "technician", world["north"])
    data = _client(tech).get("/api/v1/analytics/monitoring/").json()
    assert "situation" not in data["modes"] and "risk" not in data["modes"] and data["mode"] == "orders"


def test_geometry_helpers():
    assert geo.contains(SQUARE, 37.605, 55.705) and not geo.contains(SQUARE, 37.615, 55.705)
    assert geo.distance_m(SQUARE, NEXT) == 0 and geo.distance_m(SQUARE, FAR) > 5000
    c = geo.centroid(BUILDING)
    assert 37.604 < c[0] < 37.605 and 55.704 < c[1] < 55.7045
    assert 3000 < geo.area_m2(BUILDING) < 4000
    with pytest.raises(geo.GeoError):
        geo.validate_polygon({"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]})


def test_detect_building_prefers_the_building_under_the_point(monkeypatch, world):
    def fake(query):
        way = lambda i, poly: {  # noqa: E731
            "id": i,
            "tags": {"addr:street": "Бауманская", "addr:housenumber": str(i)},
            "geometry": [{"lon": x, "lat": y} for x, y in poly["coordinates"][0]],
        }
        return [way(1, NEXT), way(2, BUILDING)]

    monkeypatch.setattr(geo, "_overpass", fake)
    found = (
        _client(world["head"])
        .get("/api/v1/topology/detect-building/", {"lon": 37.6045, "lat": 55.7042})
        .json()
    )
    assert found["source"] == "osm:way/2" and found["exact"] and found["address"] == "Бауманская 2"


def test_seed_geo_offline_places_everything(tree, make_user):
    # строчная буква сортируется после названий зон: вставка зон сдвигает путь этого объекта
    Node.objects.get(pk=tree["district"].pk).add_child(name="объект Ярус", kind=NodeKind.COMPLEX)
    call_command("seed_geo", "--offline")
    zones = Node.objects.filter(kind=NodeKind.ZONE)
    assert zones.count() == 2
    assert all(o.geometry for o in Node.objects.filter(kind=NodeKind.COMPLEX))
    assert all(
        any(o.path.startswith(z.path) for z in zones) for o in Node.objects.filter(kind=NodeKind.COMPLEX)
    )
    call_command("seed_geo", "--offline")  # повтор ничего не ломает
    assert Node.objects.filter(kind=NodeKind.ZONE).count() == 2
