"""Графики ТО и ТР и план-графики ППР: генерация, файлы заказчика, сверка, заявки по графику."""

from datetime import date
from itertools import pairwise
from pathlib import Path

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.assets.models import Equipment
from apps.workorders import schedules as sch
from apps.workorders.models import MaintenanceNorm, MaintenanceSchedule, WorkOrder
from apps.workorders.regulation import seed_norms

DATA = Path(__file__).resolve().parents[4] / "data"
TO_FILE = DATA / "График_ТО_АКМ_и_ДУ_на_2026г_РЭК_3_на_А4.xlsx"
PPR_FILE = DATA / "График ППР АКМ на 2026г. РЭК.xlsx"


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_months_follow_customer_pattern():
    # как у заказчика (объект 1, БУиК): ТР в ноябре, ТО через месяц в нечётные месяцы
    assert sch.months_for(10, 6, 1) == {"11": "ТО+ТР", "9": "ТО", "7": "ТО", "5": "ТО", "3": "ТО", "1": "ТО"}
    # кабельные линии: два раза в год, одно с ТР
    assert sch.months_for(10, 2, 1) == {"11": "ТО+ТР", "5": "ТО"}
    assert sch.months_for(0, 4, 1) == {"1": "ТО+ТР", "10": "ТО", "7": "ТО", "4": "ТО"}


def test_plan_balances_months():
    groups = [sch.Group(f"Объект {i}", "МУСБ", 10, "шт.", 4) for i in range(12)]
    sch.plan_to_tr(groups)
    load = sch.monthly_load(groups)
    assert max(load) - min(load) <= 1 and sum(load) == 48
    # у каждого объекта ровно одно ТО+ТР
    assert all(sum(v == "ТО+ТР" for v in g.months.values()) == 1 for g in groups)


def test_ppr_cycle_sequential_and_working_days():
    items = [sch.PprItem(f"Объект {i}", n) for i, n in enumerate([56, 13, 62, 47, 102, 34, 12, 101, 6, 8])]
    sch.plan_ppr(items, 2026)
    calendar = set(sch.working_days(2026))
    spans: dict[int, tuple] = {}
    for it in items:
        start, end = spans.get(it.batch, (it.dismantle_on, it.acceptance_on))
        spans[it.batch] = (min(start, it.dismantle_on), max(end, it.acceptance_on))
    ordered = [spans[b] for b in sorted(spans)]
    for (_, end), (start, _) in pairwise(ordered):
        assert start > end, "партии идут одна за другой"
    for it in items:
        assert it.dismantle_on in calendar and it.delivery_on in calendar
        assert it.delivery_on == sch.add_wd(it.dismantle_on, 1, sorted(calendar))
        assert it.pickup_on > it.delivery_on and it.acceptance_on > it.pickup_on
    # мелкий объект едет в партии с соседним
    assert items[1].batch == items[0].batch and items[6].batch == items[5].batch
    assert date(2026, 1, 12) <= items[0].dismantle_on  # после новогодних праздников


@pytest.mark.skipif(not TO_FILE.exists(), reason="нет файла графика заказчика")
def test_customer_to_tr_file(db):
    seed_norms()
    schedule = sch.import_customer(TO_FILE.read_bytes(), TO_FILE.name, None)
    assert schedule.kind == "to_tr" and schedule.year == 2026
    # 24 объекта; шапки страниц А4 и продолжения объектов в строки не превращаются
    assert schedule.stats["objects"] == 24 and schedule.lines.count() == 140
    assert not schedule.lines.filter(type_name__in=["Марка", "Вид оборудования"]).exists()
    result = sch.validate(schedule)
    # регламент по видам воспроизводит периодичность графика заказчика почти во всех строках
    assert result["periodicity_match"] >= 0.8
    assert sch.derive_norms(schedule)["updated"] >= 10
    assert MaintenanceNorm.objects.get(type_name="Газоанализаторы").visits_per_year == 6
    content = sch.export_xlsx(schedule)
    assert content[:2] == b"PK"


@pytest.mark.skipif(not PPR_FILE.exists(), reason="нет файла ППР заказчика")
def test_customer_ppr_file(db):
    schedule = sch.import_customer(PPR_FILE.read_bytes(), PPR_FILE.name, None)
    assert schedule.kind == "ppr" and schedule.stats["sensors"] == 1008
    assert schedule.stats["batches"] == 16
    result = sch.validate(schedule)
    assert result["last_acceptance_generated"] <= "2026-12-31"
    assert sch.export_xlsx(schedule)[:2] == b"PK"


def test_generate_approve_and_plan_line(tree, make_user):
    seed_norms()
    for i in range(3):
        Equipment.objects.create(
            kind="sensor", node=tree["house"], name=f"Метан {i}", type_name="Газоанализаторы", system="АКМ"
        )
    Equipment.objects.create(
        kind="cabinet",
        node=tree["house"],
        name="Кабель",
        type_name="Кабельные линии АКМ",
        quantity=1200,
        unit="м.",
    )
    engineer = make_user("eng", "maintenance_engineer", tree["complex"])
    client = _client(engineer)
    year = timezone.localdate().year
    to_tr = client.post(
        "/api/v1/workorders/schedules/generate/", {"kind": "to_tr", "year": year}, format="json"
    )
    assert to_tr.status_code == 201, to_tr.content
    detail = client.get(f"/api/v1/workorders/schedules/{to_tr.json()['id']}/").json()
    by_type = {ln["type_name"]: ln for ln in detail["lines"]}
    assert by_type["Газоанализаторы"]["quantity"] == 3 and len(by_type["Газоанализаторы"]["months"]) == 6
    assert (
        by_type["Кабельные линии АКМ"]["unit"] == "м." and len(by_type["Кабельные линии АКМ"]["months"]) == 2
    )
    assert detail["lines"][0]["object_label"] == "Объект Альфа"  # по объекту, а не по его части
    ppr = client.post("/api/v1/workorders/schedules/generate/", {"kind": "ppr", "year": year}, format="json")
    assert ppr.status_code == 201 and ppr.json()["stats"]["sensors"] == 3
    assert client.get(f"/api/v1/workorders/schedules/{to_tr.json()['id']}/xlsx/").status_code == 200

    # утверждает руководитель; инженер — нет
    assert client.post(f"/api/v1/workorders/schedules/{to_tr.json()['id']}/approve/").status_code == 403
    head = make_user("head", "head", tree["complex"])
    assert (
        _client(head).post(f"/api/v1/workorders/schedules/{to_tr.json()['id']}/approve/").status_code == 200
    )

    # работы утверждённого графика на ближайшие месяцы — в плане ТО, «в план» создаёт заявку
    schedule = MaintenanceSchedule.objects.get(pk=to_tr.json()["id"])
    line = schedule.lines.get(type_name="Газоанализаторы")
    month = timezone.localdate().month
    line.months = {str(month): "ТО"}
    line.save()
    plan = client.get("/api/v1/workorders/maintenance/plan/").json()
    due = [r for r in plan["schedule_due"] if r["id"] == line.pk]
    assert due and due[0]["work"] == "ТО" and due[0]["planned"] is None
    response = client.post(
        "/api/v1/workorders/maintenance/schedule/",
        {"schedule_line": line.pk, "date": timezone.localdate().isoformat()},
        format="json",
    )
    assert response.status_code == 201, response.content
    order = WorkOrder.objects.get(pk=response.json()["id"])
    assert order.schedule_line == line and order.work_type == "calibration"
    assert "Газоанализаторы: 3 шт." in order.description


def test_norms_edit_rights(tree, make_user):
    seed_norms()
    norm = MaintenanceNorm.objects.get(type_name="МУСБ")
    disp = make_user("disp", "unit_dispatcher", tree["complex"])
    assert (
        _client(disp)
        .patch(f"/api/v1/workorders/norms/{norm.pk}/", {"visits_per_year": 2}, format="json")
        .status_code
        == 403
    )
    engineer = make_user("eng", "maintenance_engineer", tree["complex"])
    response = _client(engineer).patch(
        f"/api/v1/workorders/norms/{norm.pk}/", {"visits_per_year": 2}, format="json"
    )
    assert response.status_code == 200 and response.json()["source"] == "правка инженера ТО"
