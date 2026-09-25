from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.assets.models import Channel
from apps.audit.models import ActionLog
from apps.incidents import services as incidents
from apps.incidents.models import Alert, DecisionCause, DecisionOutcome, IncidentType
from apps.training import services
from apps.training.models import TrainingSession
from apps.workorders.models import WorkOrder


@pytest.fixture
def commands(monkeypatch, settings):
    settings.CONTOUR = "training"
    sent = []
    monkeypatch.setattr(services, "send_simulator", sent.append)
    return sent


@pytest.fixture(autouse=True)
def _reasons(db):
    from apps.incidents.models import DecisionReason

    DecisionReason.objects.get_or_create(
        code="resolved-remote",
        defaults={"name": "Устранено дистанционно", "outcome": DecisionOutcome.RESOLVED},
    )
    from apps.forecasting.feedback import seed_rules

    seed_rules()


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _alert(tree, type_=IncidentType.FIRE, picket=12, ext=1):
    channel = Channel.objects.create(
        external_id=ext, node=tree["house"], name=f"ДД ПК{picket}", picket=Decimal(picket)
    )
    return incidents.raise_alert(
        type=type_, severity="high", node=tree["house"], channel=channel, title="x", source=Alert.Source.RULE
    ).incident


def _steps(session):
    return {s["code"]: s["status"] for s in services.serialize(session)["steps"]}


def test_polygon_lessons_only_in_training_contour(tree, make_user, settings):
    settings.CONTOUR = "combat"
    disp = make_user("disp", "unit_dispatcher", tree["complex"])
    with pytest.raises(services.TrainingError):
        services.start(disp, "dispatcher-fire")
    # экскурсия по интерфейсу доступна и в рабочем контуре
    body = _client(disp).post("/api/v1/training/sessions/", {"lesson": "tour"}, format="json")
    assert body.status_code == 201 and body.json()["steps"][0]["status"] == "current"
    lessons = {
        item["code"]: item for item in _client(disp).get("/api/v1/training/lessons/").json()["lessons"]
    }
    assert lessons["tour"]["available"] and not lessons["dispatcher-fire"]["available"]
    assert "head-approve" not in lessons  # урок руководителя диспетчеру не показывается


def test_dispatcher_fire_lesson_checks_real_actions(tree, make_user, commands):
    from apps.workorders.services import draft_from_incident

    disp = make_user("disp", "unit_dispatcher", tree["complex"])
    tree["complex"].external_id = 900100
    tree["complex"].save()
    old = _alert(tree, ext=99)  # карточка прошлого занятия
    session = services.start(disp, "dispatcher-fire")
    old.refresh_from_db()
    assert old.status == "closed"  # объект приведён в исходное состояние
    assert [c["op"] for c in commands] == ["restore", "scenario"] and commands[1]["object"] == 900100

    assert _steps(services.evaluate(session))["incident"] == "current"
    incident = _alert(tree)
    session = services.evaluate(session)
    assert _steps(session)["incident"] == "done" and session.context["incident"] == incident.pk

    ActionLog.objects.create(user=disp, action="incident.view", object_id=str(incident.pk))
    incident = incidents.take(incident, disp)
    session = services.evaluate(session)
    assert _steps(session)["take"] == "done" and _steps(session)["decide"] == "current"
    assert services.serialize(session)["steps"][3]["route"] == f"/incidents/{incident.pk}"

    # неверная причина: шаг не засчитан, ученик видит объяснение, ошибка учтена
    incidents.decide(
        incident, disp, outcome=DecisionOutcome.BRIGADE_DISPATCHED, cause=DecisionCause.SENSOR_FAULT
    )
    session = services.evaluate(session)
    assert _steps(session)["decide"] == "current" and session.mistakes == 1
    assert "Неисправность датчика" in services.serialize(session)["note"]
    session = services.evaluate(session)
    assert session.mistakes == 1  # то же решение повторно не штрафуется

    incidents.decide(
        incident, disp, outcome=DecisionOutcome.BRIGADE_DISPATCHED, cause=DecisionCause.REAL_EVENT
    )
    draft_from_incident(incident, disp)
    session = services.evaluate(session)
    assert session.status == TrainingSession.Status.DONE and services.serialize(session)["note"] is None


def test_head_lesson_second_party_drafts_order(tree, make_user, commands):
    head = make_user("head", "head", tree["district"])
    session = services.start(head, "head-approve")
    assert session.node == tree["complex"]  # у районной роли — первый объект зоны
    incident = _alert(tree, IncidentType.GAS)
    session = services.evaluate(session)
    order = WorkOrder.objects.get(pk=session.context["workorder"])
    assert order.incident == incident and order.created_by.username == services.BOT_USERNAME
    assert _steps(session)["find"] == "current"
    with pytest.raises(services.TrainingError):
        services.confirm(session, "approve")  # засчитывается только по действию
    session = services.confirm(session, "find")

    from apps.workorders.services import transition

    transition(order, WorkOrder.Status.APPROVED, head)
    assert _steps(services.evaluate(session))["approve"] == "done"
    WorkOrder.objects.filter(pk=order.pk).update(status=WorkOrder.Status.SUBMITTED)
    assert services.evaluate(session).status == TrainingSession.Status.DONE


def test_technician_lesson(tree, make_user, commands):
    from apps.workorders.services import transition

    tech = make_user("tech", "technician", tree["complex"])
    session = services.start(tech, "technician-order")
    order = WorkOrder.objects.get(pk=session.context["workorder"])
    assert order.assignee == tech and order.status == WorkOrder.Status.SUBMITTED
    services.confirm(session, "find")
    transition(order, WorkOrder.Status.IN_PROGRESS, tech)
    transition(order, WorkOrder.Status.DONE, tech)
    body = _client(tech).get("/api/v1/training/sessions/current/").json()
    assert body["status"] == "done" and body["mistakes"] == 0


def test_analyst_lesson_gets_pending_label(tree, make_user, commands):
    from apps.forecasting.feedback import review
    from apps.forecasting.models import FeedbackLabel

    analyst = make_user("analyst", "analyst", tree["district"])
    session = services.start(analyst, "analyst-labels")
    incident = _alert(tree, IncidentType.SENSOR_FAILURE)
    session = services.evaluate(session)
    labels = FeedbackLabel.objects.filter(incident=incident)
    assert labels.filter(status=FeedbackLabel.Status.PENDING).exists()  # решение бота — метка на проверку
    review(labels, analyst, FeedbackLabel.Status.ACCEPTED)
    session = services.evaluate(session)
    assert _steps(session) == {"incident": "done", "label": "done", "health": "current"}


def test_starting_again_abandons_and_results_visible_to_head(tree, make_user, commands):
    disp = make_user("disp", "unit_dispatcher", tree["complex"])
    head = make_user("head", "head", tree["district"])
    stranger = make_user("beta", "unit_dispatcher", tree["other"])
    tree["complex"].external_id = 900100
    tree["complex"].save()
    first = services.start(disp, "dispatcher-intrusion")
    services.start(disp, "dispatcher-fire")
    first.refresh_from_db()
    assert first.status == TrainingSession.Status.ABANDONED
    assert commands[-1]["op"] == "scenario" and any(c["op"] == "restore" for c in commands[2:])
    services.start(stranger, "tour")
    services.abandon(TrainingSession.objects.get(user=stranger))

    results = _client(head).get("/api/v1/training/sessions/").json()
    assert {r["user"] for r in results} >= {"disp"}
    assert _client(disp).get("/api/v1/training/sessions/").json()[0]["lesson"] == "dispatcher-intrusion"
    # чужой дисп не видит результаты коллеги
    assert all(r["lesson"] == "tour" for r in _client(stranger).get("/api/v1/training/sessions/").json())
