import pytest
from rest_framework.test import APIClient

from apps.audit.models import ActionLog
from apps.incidents import services
from apps.incidents.first import backfill
from apps.incidents.models import Alert, Decision, DecisionOutcome, Incident, IncidentEvent, IncidentType


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def shift(tree, make_user):
    return {
        "petrov": make_user("petrov", "unit_dispatcher", tree["complex"]),
        "kozlova": make_user("kozlova", "ods_dispatcher", tree["district"]),
        "head": make_user("head", "head", tree["district"]),
        "incident": services.raise_alert(
            type=IncidentType.FIRE, severity="high", node=tree["house"], title="Дым", source=Alert.Source.RULE
        ).incident,
    }


def test_first_to_respond_owns_the_card(shift):
    incident, petrov, kozlova = shift["incident"], shift["petrov"], shift["kozlova"]
    url = f"/api/v1/incidents/items/{incident.pk}/"
    _client(petrov).get(url)  # Петров заметил первым
    _client(kozlova).get(url)
    assert _client(kozlova).post(url + "acknowledge/").status_code == 200  # а откликнулась первой Козлова
    incident.refresh_from_db()
    assert incident.first_seen_by == petrov
    assert incident.responder == kozlova and incident.assigned_to == kozlova
    lost = _client(petrov).post(url + "take/")
    assert lost.status_code == 409 and "откликнулся первым" in lost.json()["detail"]
    assert "Козлова" in lost.json()["detail"] or "kozlova" in lost.json()["detail"]


def test_head_view_is_not_first_seen(shift):
    incident = shift["incident"]
    _client(shift["head"]).get(f"/api/v1/incidents/items/{incident.pk}/")
    incident.refresh_from_db()
    assert incident.first_seen_by is None


def test_any_action_on_a_free_card_claims_it(shift):
    incident, petrov, kozlova = shift["incident"], shift["petrov"], shift["kozlova"]
    services.decide(incident, petrov, outcome=DecisionOutcome.CHECK_REQUESTED)
    incident.refresh_from_db()
    assert incident.assigned_to == petrov and incident.responder == petrov
    with pytest.raises(services.IncidentError):
        services.mark_action(incident, kozlova, incident.actions[0]["code"])
    # чужую карточку нельзя «откликнуться» черновиком заявки
    body = _client(kozlova).post(f"/api/v1/workorders/items/from-incident/{incident.pk}/")
    assert body.status_code == 409


def test_head_acts_and_takes_over_without_changing_first_responder(shift):
    incident, petrov, head = shift["incident"], shift["petrov"], shift["head"]
    services.take(incident, petrov)
    services.mark_action(incident, head, incident.actions[0]["code"])  # руководитель помогает, не забирая
    incident.refresh_from_db()
    assert incident.assigned_to == petrov
    services.take(incident, head, force=True)
    incident.refresh_from_db()
    assert incident.assigned_to == head and incident.responder == petrov
    event = IncidentEvent.objects.filter(incident=incident, payload__takeover_from=petrov.pk).get()
    assert event.text.startswith("Перехват у")


def test_release_keeps_first_responder(shift):
    incident, petrov, kozlova = shift["incident"], shift["petrov"], shift["kozlova"]
    services.take(incident, petrov)
    services.release(incident, petrov)
    services.take(incident, kozlova)
    incident.refresh_from_db()
    assert incident.assigned_to == kozlova and incident.responder == petrov


def test_backfill_from_history(shift):
    incident, petrov, kozlova = shift["incident"], shift["petrov"], shift["kozlova"]
    ActionLog.objects.create(user=kozlova, action="incident.view", object_id=str(incident.pk))
    IncidentEvent.objects.create(incident=incident, kind="assigned", actor=petrov)
    Incident.objects.filter(pk=incident.pk).update(responder=None, responded_at=None, first_seen_at=None)
    assert backfill(Incident, ActionLog, IncidentEvent, Decision) == 1
    incident.refresh_from_db()
    assert incident.first_seen_by == kozlova and incident.responder == petrov
