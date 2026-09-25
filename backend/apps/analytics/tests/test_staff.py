from datetime import UTC, datetime, timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Team, TeamKind
from apps.analytics.staff import my_metrics, shift_key, staff_metrics
from apps.audit.models import ActionLog
from apps.incidents import services
from apps.incidents.models import Alert, DecisionOutcome, IncidentType


def _card(tree, type_=IncidentType.FIRE, node="house"):
    return services.raise_alert(
        type=type_, severity="high", node=tree[node], title="x", source=Alert.Source.RULE
    ).incident


def _view(user, incident):
    ActionLog.objects.create(user=user, action="incident.view", object_id=str(incident.pk))
    from apps.incidents.first import mark_seen

    mark_seen(incident, user)


def test_shift_keys():
    assert shift_key(datetime(2026, 6, 1, 6, tzinfo=UTC)) == "2026-06-01 день"  # 09:00 МСК
    assert shift_key(datetime(2026, 6, 1, 18, tzinfo=UTC)) == "2026-06-01 ночь"  # 21:00 МСК
    assert shift_key(datetime(2026, 6, 1, 23, tzinfo=UTC)) == "2026-06-01 ночь"  # 02:00 МСК следующих суток


def test_race_quality_takeover_and_training(tree, make_user):
    from apps.training.models import TrainingSession

    petrov = make_user("petrov", "unit_dispatcher", tree["complex"])
    kozlova = make_user("kozlova", "ods_dispatcher", tree["district"])
    head = make_user("head", "head", tree["district"])
    team = Team.objects.create(
        code="u", name="Диспетчерская Альфы", kind=TeamKind.UNIT, scope_node=tree["complex"]
    )
    petrov.team = team
    petrov.save()

    race = _card(tree)
    _view(petrov, race)
    _view(kozlova, race)
    services.acknowledge(race, kozlova)  # Петров заметил первым, но откликнулась первой Козлова

    hasty = _card(tree, IncidentType.GAS)
    services.take(hasty, petrov)
    services.decide(hasty, petrov, outcome=DecisionOutcome.FALSE_ALARM)
    repeat = _card(tree, IncidentType.GAS)  # газ на том же объекте вернулся в течение суток
    services.take(repeat, petrov)
    services.take(repeat, head, force=True)

    TrainingSession.objects.create(
        user=petrov, lesson="dispatcher-fire", status="done", finished_at=timezone.now(), mistakes=2
    )
    now = timezone.now()
    data = staff_metrics(head, now - timedelta(days=1), now + timedelta(hours=1))
    people = {p["name"]: p for p in data["people"]}
    p, k = people["petrov"], people["kozlova"]
    assert p["first_seen"] == 1 and p["responded"] == 2 and p["races"] == 1 and p["races_won"] == 0
    assert k["responded"] == 1 and k["races_won"] == 1 and k["races_won_share"] == 1.0
    assert p["closed"] == 1 and p["repeated"] == 1 and p["quality"] == 0.0
    assert p["takeovers_lost"] == 1 and p["training_done"] == 1 and p["training_mistakes"] == 2
    assert p["zone_cards"] == 3 and abs(p["responded_share"] - 2 / 3) < 0.01
    assert p["rank"] == 1 and k["rank"] == 2 and p["shifts"] >= 1
    assert data["summary"]["contested"] == 1 and data["summary"]["takeovers"] == 1
    assert data["teams"][0]["team"] == "Диспетчерская Альфы" and data["teams"][0]["responded"] == 2

    mine = my_metrics(kozlova, now - timedelta(days=1), now + timedelta(hours=1))
    assert mine["me"]["rank"] == 2 and mine["rank_of"] == 2 and mine["colleagues"]["responded"] == 2


def test_scope_and_api(tree, make_user):
    beta = make_user("beta", "unit_dispatcher", tree["other"])
    alpha = make_user("alpha", "unit_dispatcher", tree["complex"])
    card = _card(tree)
    services.take(card, alpha)
    client = APIClient()
    client.force_authenticate(beta)
    day = timezone.localdate().isoformat()
    body = client.get("/api/v1/analytics/staff/", {"from": day, "to": day}).json()
    assert body["summary"]["cards"] == 0 and {p["name"] for p in body["people"]} == {"beta"}
    client.force_authenticate(alpha)
    me = client.get("/api/v1/analytics/staff/me/", {"from": day, "to": day}).json()
    assert me["me"]["responded"] == 1 and me["me"]["rank"] == 1
