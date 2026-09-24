from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.analytics.efficiency import efficiency
from apps.analytics.quality import quality
from apps.assets.models import Channel
from apps.audit.models import ActionLog
from apps.forecasting.models import Prediction
from apps.incidents import services
from apps.incidents.models import Alert, DecisionOutcome, Incident, IncidentType


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def handled(tree, make_user):
    """Карточка, которую диспетчер открыл, взял и решил с указанием причины."""
    user = make_user("disp", "unit_dispatcher", tree["complex"])
    ch = Channel.objects.create(external_id=1, node=tree["house"], name="Дым 1")
    incident = services.raise_alert(
        type=IncidentType.FIRE,
        severity="high",
        node=tree["house"],
        channel=ch,
        title="x",
        source=Alert.Source.RULE,
    ).incident
    t0 = timezone.now() - timedelta(hours=1)
    Incident.objects.filter(pk=incident.pk).update(opened_at=t0)
    ActionLog.objects.create(
        user=user, action="incident.view", object_type="incidents.incident", object_id=str(incident.pk)
    )
    ActionLog.objects.filter(action="incident.view").update(ts=t0 + timedelta(minutes=3))
    incident.refresh_from_db()
    services.take(incident, user)
    services.decide(incident, user, outcome=DecisionOutcome.FALSE_ALARM, cause="false_alarm")
    return user, incident, t0


def test_efficiency_measures_reaction_times(handled):
    user, _incident, t0 = handled
    data = efficiency(user, t0 - timedelta(hours=1), timezone.now() + timedelta(minutes=1))
    s = data["summary"]
    assert s["cards"] == 1 and s["view"]["median"] == 3.0
    assert 59 <= s["decision"]["median"] <= 61  # решение принято «сейчас», карточка открыта час назад
    assert s["closed_with_result_share"] == 1.0 and s["escalated_share"] == 0
    assert data["causes"] == [{"cause": "false_alarm", "title": "Ложное срабатывание", "count": 1}]
    assert data["staff"][0]["decisions"] == 1 and data["staff"][0]["with_cause_share"] == 1.0


def test_emulated_cards_can_be_excluded(handled):
    user, incident, t0 = handled
    Incident.objects.filter(pk=incident.pk).update(is_emulated=True)
    period = (t0 - timedelta(hours=1), timezone.now() + timedelta(minutes=1))
    assert efficiency(user, *period)["emulated"] == 1
    assert efficiency(user, *period, include_emulated=False)["summary"]["cards"] == 0


def test_quality_precision_from_journal(tree, make_user):
    user = make_user("an", "analyst", tree["complex"])
    now = timezone.now()
    for outcome in ("confirmed", "not_confirmed", "not_confirmed", "pending"):
        Prediction.objects.create(
            task="gas",
            node=tree["house"],
            issued_at=now - timedelta(hours=2),
            horizon_hours=24,
            valid_until=now + timedelta(hours=22),
            probability=0.2,
            risk_level="high",
            outcome=outcome,
        )
    data = quality(user, now - timedelta(days=1), now)
    gas = data["tasks"]["gas"]
    assert gas["total"] == 4 and gas["precision"] == round(1 / 3, 3) and gas["false_share"] == round(2 / 3, 3)
    assert data["tasks"]["fire"]["total"] == 0


@pytest.mark.parametrize("fmt, magic", [("pdf", b"%PDF"), ("xlsx", b"PK")])
def test_report_is_generated_and_downloaded(handled, make_user, tree, fmt, magic, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    head = make_user("head", "head", tree["district"])
    client = _client(head)
    day = timezone.localdate().isoformat()
    created = client.post(
        "/api/v1/analytics/reports/",
        {"format": fmt, "from": day, "to": day, "include_emulated": True},
        format="json",
    )
    assert created.status_code == 201, created.content
    body = b"".join(
        client.get(f"/api/v1/analytics/reports/{created.json()['id']}/download/").streaming_content
    )
    assert body.startswith(magic)


def test_dispatcher_cannot_export(handled):
    user, *_ = handled
    response = _client(user).post("/api/v1/analytics/reports/", {"format": "pdf"}, format="json")
    assert response.status_code == 403
