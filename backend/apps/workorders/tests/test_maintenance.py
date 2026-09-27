"""Инженер ТО: план по регламенту и состоянию, постановка в план, фактическое состояние от бригады."""

from datetime import date, timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from apps.assets.models import Equipment
from apps.workorders.models import EquipmentInspection, MaintenanceRecommendation, WorkOrder


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _pump(tree, days_since=120, interval=90, **extra):
    return Equipment.objects.create(
        kind="pump",
        node=tree["house"],
        name="Насос АНС-1",
        inventory_number="НС-1",
        last_maintenance_at=timezone.localdate() - timedelta(days=days_since),
        maintenance_interval_days=interval,
        **extra,
    )


def test_plan_shows_overdue_and_schedule_creates_draft(tree, make_user):
    pump = _pump(tree)
    fresh = _pump(tree, days_since=10)  # следующее ТО через 80 суток — в плане, но не просрочено
    engineer = make_user("eng", "maintenance_engineer", tree["complex"])
    client = _client(engineer)
    plan = client.get("/api/v1/workorders/maintenance/plan/").json()
    overdue = [r for r in plan["due"] if r["overdue_days"]]
    assert [r["name"] for r in overdue] == ["Насос АНС-1"] and overdue[0]["overdue_days"] == 30
    assert plan["kpis"]["unplanned_overdue"] == 1
    assert fresh.pk in {r["id"] for r in plan["due"]}

    day = (timezone.localdate() + timedelta(days=3)).isoformat()
    response = client.post("/api/v1/workorders/maintenance/schedule/", {"equipment": pump.pk, "date": day})
    assert response.status_code == 201
    order = WorkOrder.objects.get(pk=response.json()["id"])
    assert order.status == "draft" and order.equipment == pump and order.work_type == "pump_service"
    assert timezone.localtime(order.due_at).date().isoformat() == day

    plan = client.get("/api/v1/workorders/maintenance/plan/").json()
    assert plan["kpis"]["unplanned_overdue"] == 0 and plan["planned"][0]["number"] == order.number
    xlsx = client.get("/api/v1/workorders/maintenance/plan/", {"export": "xlsx"})
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_plan_is_scoped_and_role_guarded(tree, make_user):
    _pump(tree)
    other = make_user("eng2", "maintenance_engineer", tree["other"])
    assert _client(other).get("/api/v1/workorders/maintenance/plan/").json()["due"] == []
    tech = make_user("tech", "technician", tree["complex"])
    assert _client(tech).get("/api/v1/workorders/maintenance/plan/").status_code == 403
    disp = make_user("disp", "unit_dispatcher", tree["complex"])
    assert _client(disp).get("/api/v1/workorders/maintenance/plan/").status_code == 403


def test_schedule_recommendation_with_date(tree, make_user):
    rec = MaintenanceRecommendation.objects.create(
        node=tree["house"], work_type="calibration", priority="high", due_date=date.today(), rationale="Метан"
    )
    head = make_user("head", "head", tree["complex"])
    day = (timezone.localdate() + timedelta(days=7)).isoformat()
    response = _client(head).post(
        "/api/v1/workorders/maintenance/schedule/", {"recommendation": rec.pk, "date": day}
    )
    assert response.status_code == 201
    rec.refresh_from_db()
    assert rec.status == "accepted"


def test_brigade_records_condition_and_maintenance(tree, make_user):
    pump = _pump(tree)
    tech = make_user("tech", "technician", tree["complex"])
    order = WorkOrder.objects.create(
        number="ЗН-1",
        node=tree["house"],
        equipment=pump,
        work_type="pump_service",
        priority="medium",
        title="ТО насоса",
        description="",
        due_at=timezone.now(),
        assignee=tech,
        status=WorkOrder.Status.IN_PROGRESS,
    )
    response = _client(tech).post(
        f"/api/v1/workorders/items/{order.pk}/transition/",
        {
            "status": "done",
            "report": "Насос обслужен",
            "condition": "needs_repair",
            "notes": "Износ подшипника",
        },
    )
    assert response.status_code == 200, response.content
    pump.refresh_from_db()
    assert pump.condition == "needs_repair" and pump.last_maintenance_at == timezone.localdate()
    inspection = EquipmentInspection.objects.get()
    assert inspection.workorder == order and inspection.maintenance and inspection.notes == "Износ подшипника"

    # состояние «требует ремонта» порождает рекомендацию, «исправно» после осмотра её закрывает
    from apps.workorders.recommendations import generate

    generate()
    rec = MaintenanceRecommendation.objects.get(equipment=pump, rationale__startswith="По последнему осмотру")
    assert rec.priority == "high"
    engineer = make_user("eng", "maintenance_engineer", tree["complex"])
    response = _client(engineer).post(
        "/api/v1/workorders/inspections/",
        {"equipment": pump.pk, "condition": "good", "notes": "Подшипник заменён"},
    )
    assert response.status_code == 201
    rec.refresh_from_db()
    assert rec.status == "done"


def test_done_requires_in_progress_and_valid_condition(tree, make_user):
    tech = make_user("tech", "technician", tree["complex"])
    order = WorkOrder.objects.create(
        number="ЗН-2",
        node=tree["house"],
        work_type="inspection",
        priority="low",
        title="Осмотр",
        description="",
        due_at=timezone.now(),
        assignee=tech,
        status=WorkOrder.Status.SUBMITTED,
    )
    url = f"/api/v1/workorders/items/{order.pk}/transition/"
    assert _client(tech).post(url, {"status": "done"}).status_code == 409
    order.status = WorkOrder.Status.IN_PROGRESS
    order.save()
    assert _client(tech).post(url, {"status": "done", "condition": "broken"}).status_code == 409
    assert _client(tech).post(url, {"status": "done", "report": "Ок"}).status_code == 200


def test_engineer_workspace(tree, make_user):
    _pump(tree)
    engineer = make_user("eng", "maintenance_engineer", tree["complex"])
    body = _client(engineer).get("/api/v1/analytics/workspace/").json()
    assert body["role"] == "maintenance_engineer" and body["title"] == "Инженер ТО"
    kpis = {k["key"]: k["value"] for k in body["kpis"]}
    assert kpis["overdue"] == 1
    assert body["lists"]["maintenance_due"][0]["name"] == "Насос АНС-1"
