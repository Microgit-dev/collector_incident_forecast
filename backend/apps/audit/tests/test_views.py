import pytest
from rest_framework.test import APIClient

from apps.audit.models import ActionLog
from apps.forecasting.models import RiskLevel
from apps.incidents import services
from apps.incidents.models import Alert, IncidentType


@pytest.fixture
def incident(tree):
    return services.raise_alert(
        type=IncidentType.SENSOR_FAILURE,
        severity=RiskLevel.MEDIUM,
        node=tree["house"],
        title="Неисправность датчика",
        source=Alert.Source.RULE,
    ).incident


def test_card_view_is_logged_once_per_window_and_listed(tree, make_user, incident):
    petrov = make_user("petrov", "unit_dispatcher", tree["house"])
    head = make_user("head", "head", tree["district"])
    client = APIClient()
    for user in (petrov, petrov, head):
        client.force_authenticate(user)
        body = client.get(f"/api/v1/incidents/items/{incident.pk}/").json()

    assert ActionLog.objects.filter(action="incident.view", object_id=str(incident.pk)).count() == 2
    assert [v["username"] for v in body["viewed_by"]] == ["petrov", "head"]


def test_foreign_scope_cannot_open_card(tree, make_user, incident):
    client = APIClient()
    client.force_authenticate(make_user("beta", "unit_dispatcher", tree["other"]))
    assert client.get(f"/api/v1/incidents/items/{incident.pk}/").status_code == 404
    assert not ActionLog.objects.filter(action="incident.view").exists()
