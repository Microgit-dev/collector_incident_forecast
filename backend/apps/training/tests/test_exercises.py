from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.incidents import services as incidents
from apps.incidents.models import Alert, DecisionOutcome, IncidentType
from apps.notifications.models import Notification
from apps.training import exercises, services
from apps.training.models import Exercise


@pytest.fixture
def sim(monkeypatch, settings):
    settings.CONTOUR = "training"
    sent = []
    monkeypatch.setattr(services, "send_simulator", sent.append)
    monkeypatch.setattr(exercises, "send_simulator", sent.append)
    return sent


@pytest.fixture
def crew(tree, make_user):
    tree["complex"].external_id = 900001
    tree["complex"].save(update_fields=["external_id"])
    return {
        "head": make_user("head", "head", tree["district"]),
        "petrov": make_user("petrov", "unit_dispatcher", tree["complex"]),
        "ivanov": make_user("ivanov", "unit_dispatcher", tree["complex"]),
        "brigade": make_user("brigade", "technician", tree["complex"]),
    }


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _create(crew, tree, **extra):
    body = {
        "scenario": "fire",
        "node": tree["complex"].pk,
        "participants": [crew["petrov"].pk, crew["ivanov"].pk],
        **extra,
    }
    return _client(crew["head"]).post("/api/v1/exercises/", body, format="json")


def test_only_in_training_contour(crew, tree, settings):
    settings.CONTOUR = "combat"
    response = _create(crew, tree)
    assert response.status_code == 400 and "учебном контуре" in response.json()["detail"]


def test_dispatcher_cannot_set_up_exercises(crew, tree, sim):
    response = _client(crew["petrov"]).post("/api/v1/exercises/", {"scenario": "fire"}, format="json")
    assert response.status_code == 403


def test_participants_are_notified_without_spoiling_the_scenario(crew, tree, sim):
    response = _create(crew, tree, silent=[crew["ivanov"].pk], briefing="Проверка ночной смены")
    assert response.status_code == 201
    exercise = Exercise.objects.get()
    petrov = Notification.objects.get(user=crew["petrov"])
    ivanov = Notification.objects.get(user=crew["ivanov"])
    assert petrov.title.startswith("Будут учения") and "по сигналу руководителя" in petrov.body
    assert "Проверка ночной смены" in petrov.body
    assert "не реагируйте" in ivanov.body and "не реагируйте" not in petrov.body
    assert not Notification.objects.filter(user=crew["brigade"]).exists()
    # участник видит учения, но не сценарий и не чужую роль «молчащего»
    seen = _client(crew["petrov"]).get(f"/api/v1/exercises/{exercise.pk}/").json()
    assert seen["scenario"] is None and not any(p["silent"] for p in seen["participants"])
    mine = _client(crew["ivanov"]).get("/api/v1/exercises/mine/").json()
    assert mine[0]["me"]["silent"] is True
    # непричастный сотрудник учений не видит
    assert _client(crew["brigade"]).get(f"/api/v1/exercises/{exercise.pk}/").status_code == 404


def test_start_by_button_runs_the_scenario(crew, tree, sim, django_capture_on_commit_callbacks):
    exercise_id = _create(crew, tree, complication="comm").json()["id"]
    with django_capture_on_commit_callbacks(execute=True):
        response = _client(crew["head"]).post(f"/api/v1/exercises/{exercise_id}/start/")
    assert response.status_code == 200 and response.json()["status"] == "running"
    ops = [(c["op"], c.get("scenario")) for c in sim]
    assert ops[:2] == [("restore", None), ("scenario", "fire")]
    # осложнение (eager celery) — второй сценарий
    assert ("scenario", "comm") in ops
    assert Notification.objects.filter(user=crew["petrov"], title__startswith="Учения начались").exists()
    again = _client(crew["head"]).post(f"/api/v1/exercises/{exercise_id}/start/")
    assert again.status_code == 409


def test_timer_start_reminder_and_auto_finish(crew, tree, sim):
    at = timezone.now() + timedelta(minutes=10)
    exercise_id = _create(crew, tree, scheduled_at=at.isoformat(), duration_min=20).json()["id"]
    assert exercises.tick()["reminded"] == 1  # за 15 минут — напоминание
    assert exercises.tick()["reminded"] == 0  # один раз
    assert Exercise.objects.get(pk=exercise_id).status == "scheduled"
    exercises.tick(now=at + timedelta(seconds=5))
    exercise = Exercise.objects.get(pk=exercise_id)
    assert exercise.status == "running"
    exercises.tick(now=exercise.started_at + timedelta(minutes=21))
    assert Exercise.objects.get(pk=exercise_id).status == "finished"


def test_stop_early_restores_the_object(crew, tree, sim):
    exercise_id = _create(crew, tree).json()["id"]
    head = _client(crew["head"])
    head.post(f"/api/v1/exercises/{exercise_id}/start/")
    sim.clear()
    response = head.post(
        f"/api/v1/exercises/{exercise_id}/stop/", {"reason": "реальная тревога"}, format="json"
    )
    body = response.json()
    assert body["status"] == "stopped" and body["stop_reason"] == "реальная тревога"
    assert sim == [{"op": "restore", "object": 900001, "exercise": exercise_id}]
    note = Notification.objects.filter(user=crew["petrov"]).first()
    assert note.title.startswith("Учения прекращены досрочно") and "реальная тревога" in note.body
    # назначенные, но не начатые — отменяются
    other = _create(crew, tree).json()["id"]
    assert head.post(f"/api/v1/exercises/{other}/stop/").json()["status"] == "cancelled"


def test_report_checks_response_decision_and_silent_escalation(crew, tree, sim):
    exercise_id = _create(crew, tree, silent=[crew["ivanov"].pk]).json()["id"]
    head = _client(crew["head"])
    head.post(f"/api/v1/exercises/{exercise_id}/start/")
    incident = incidents.raise_alert(
        type=IncidentType.FIRE, severity="high", node=tree["house"], title="Дым", source=Alert.Source.RULE
    ).incident
    _client(crew["petrov"]).get(f"/api/v1/incidents/items/{incident.pk}/")
    incidents.take(incident, crew["petrov"])
    incidents.decide(incident, crew["petrov"], outcome=DecisionOutcome.BRIGADE_DISPATCHED)
    report = head.post(f"/api/v1/exercises/{exercise_id}/finish/").json()["report"]
    checks = {c["code"]: c["ok"] for c in report["checks"]}
    assert checks["detected"] and checks["response"] and checks["participant"] and checks["decision"]
    assert checks["dispatch"] and checks["silent"] and not checks["workorder"]
    people = {p["name"]: p for p in report["people"]}
    assert people["petrov"]["responded"] == 1 and people["petrov"]["decisions"] == 1
    assert people["ivanov"]["verdict"] == "выполнил вводную: не вмешивался"
    kinds = [r["kind"] for r in report["timeline"]]
    assert kinds[0] == "start" and "opened" in kinds and "seen" in kinds and kinds[-1] == "end"
    # после учений участник видит разбор и сценарий
    seen = _client(crew["ivanov"]).get(f"/api/v1/exercises/{exercise_id}/").json()
    assert seen["scenario"] == "fire" and seen["report"]["score"]["total"] == len(report["checks"])


def test_participant_confirms_briefing(crew, tree, sim):
    exercise_id = _create(crew, tree).json()["id"]
    body = _client(crew["petrov"]).post(f"/api/v1/exercises/{exercise_id}/confirm/").json()
    assert body["me"]["confirmed_at"] is not None
    assert _client(crew["petrov"]).post(f"/api/v1/exercises/{exercise_id}/start/").status_code == 403
