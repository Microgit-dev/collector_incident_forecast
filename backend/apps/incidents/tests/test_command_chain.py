import pytest
from rest_framework.test import APIClient

from apps.forecasting.models import RiskLevel
from apps.incidents import services
from apps.incidents.models import Alert, DecisionOutcome, Incident, IncidentType


@pytest.fixture
def staff(tree, make_user):
    return {
        "dispatcher": make_user("disp", "unit_dispatcher", tree["house"]),
        "dispatcher2": make_user("disp2", "unit_dispatcher", tree["house"]),
        "head": make_user("head", "head", tree["complex"]),
        "foreign": make_user("beta", "unit_dispatcher", tree["other"]),
    }


def _raise(tree, **kw):
    params = {
        "type": IncidentType.SENSOR_FAILURE,
        "severity": RiskLevel.MEDIUM,
        "node": tree["house"],
        "title": "Неисправность датчика",
        "source": Alert.Source.RULE,
    }
    return services.raise_alert(**(params | kw))


def test_alerts_group_into_one_incident_and_severity_bumps(tree, staff):
    first = _raise(tree)
    second = _raise(tree, severity=RiskLevel.HIGH)
    assert first.incident_id == second.incident_id
    incident = Incident.objects.get()
    assert incident.severity == RiskLevel.HIGH
    assert incident.responsible_node == tree["house"]


def test_escalation_moves_responsibility_up_the_chain(tree, staff, django_capture_on_commit_callbacks):
    incident = _raise(tree).incident
    with django_capture_on_commit_callbacks(execute=True):
        services.escalate(incident)
    incident.refresh_from_db()
    assert incident.responsible_node == tree["complex"]
    assert incident.escalation_level == 1
    assert staff["head"].notifications.exists()


def test_card_lock_prevents_parallel_work(tree, staff):
    incident = _raise(tree).incident
    services.take(incident, staff["dispatcher"])
    with pytest.raises(services.IncidentError):
        services.take(incident, staff["dispatcher2"])
    with pytest.raises(services.IncidentError):
        services.decide(incident, staff["dispatcher2"], outcome=DecisionOutcome.FALSE_ALARM)


def test_false_alarm_decision_resolves_incident(tree, staff):
    incident = _raise(tree).incident
    services.take(incident, staff["dispatcher"])
    services.decide(
        incident, staff["dispatcher"], outcome=DecisionOutcome.FALSE_ALARM, comment="плановые работы"
    )
    incident.refresh_from_db()
    assert incident.status == Incident.Status.RESOLVED
    assert incident.events.filter(kind="decision").exists()


def test_scope_limits_visibility_and_actions(tree, staff):
    _raise(tree)
    client = APIClient()

    client.force_authenticate(staff["foreign"])
    assert client.get("/api/v1/incidents/items/").json()["count"] == 0

    client.force_authenticate(staff["head"])
    listing = client.get("/api/v1/incidents/items/").json()
    assert listing["count"] == 1

    incident_id = listing["results"][0]["id"]
    client.force_authenticate(staff["dispatcher"])
    client.get(f"/api/v1/incidents/items/{incident_id}/")
    taken = client.post(f"/api/v1/incidents/items/{incident_id}/take/")
    assert taken.status_code == 200
    # ответ действия — полная карточка: интерфейс подменяет ею открытую, в том числе список просмотревших
    assert [v["username"] for v in taken.json()["viewed_by"]] == [staff["dispatcher"].username]
    client.force_authenticate(staff["dispatcher2"])
    assert client.post(f"/api/v1/incidents/items/{incident_id}/take/").status_code == 409


def test_observer_cannot_decide(tree, make_user):
    observer = make_user("obs", "observer", tree["district"])
    incident_id = _raise(tree).incident_id
    client = APIClient()
    client.force_authenticate(observer)
    assert client.get(f"/api/v1/incidents/items/{incident_id}/").status_code == 200
    response = client.post(f"/api/v1/incidents/items/{incident_id}/decide/", {"outcome": "false_alarm"})
    assert response.status_code == 403


def test_brigade_in_zone_does_not_hold_the_incident(tree, make_user):
    # в зоне только бригада — инцидент уходит к ближайшей дежурной смене выше
    make_user("brigade", "technician", tree["house"])
    make_user("head_up", "head", tree["complex"])
    incident = _raise(tree).incident
    assert incident.responsible_node == tree["complex"]
