from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient

from apps.assets.models import Channel
from apps.forecasting.models import ChannelHealth, ChannelRisk
from apps.incidents import services
from apps.incidents.models import Alert, IncidentType
from apps.workorders.models import WorkOrder, WorkType


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _setup(tree):
    near = Channel.objects.create(external_id=1, node=tree["house"], name="Дым ПК12", picket=Decimal(12))
    far = Channel.objects.create(external_id=2, node=tree["house"], name="Газ ПК80", picket=Decimal(80))
    now = timezone.now()
    ChannelRisk.objects.create(channel=far, task="gas", as_of=now, probability=0.9, risk_level="critical")
    ChannelHealth.objects.create(channel=far, computed_at=now, score=20, silent=True)
    incident = services.raise_alert(
        type=IncidentType.FIRE,
        severity="high",
        node=tree["house"],
        channel=near,
        title="Пожар",
        source=Alert.Source.RULE,
    ).incident
    return near, far, incident


def _order(tree, number, assignee=None, status=WorkOrder.Status.DRAFT, incident=None, due=timedelta(hours=4)):
    return WorkOrder.objects.create(
        number=number,
        node=tree["house"],
        incident=incident,
        work_type=WorkType.INSPECTION,
        priority="high",
        title=f"Заявка {number}",
        description="",
        due_at=timezone.now() + due,
        assignee=assignee,
        status=status,
    )


def test_each_role_gets_its_workspace(tree, make_user):
    _, _, incident = _setup(tree)
    _order(tree, "WO-1", incident=incident)
    head = make_user("head", "head", tree["complex"])
    body = _client(head).get("/api/v1/analytics/workspace/").json()
    assert body["role"] == "head" and body["map"]["workorders"] is True
    assert {k["key"]: k["value"] for k in body["kpis"]}["approvals"] == 1
    assert body["lists"]["approvals"][0]["number"] == "WO-1"

    analyst = make_user("analyst", "analyst", tree["complex"])
    body = _client(analyst).get("/api/v1/analytics/workspace/").json()
    assert body["map"]["color_by"] == "health"
    assert body["lists"]["weak_channels"][0]["name"] == "Газ ПК80"
    kpis = {k["key"]: k["value"] for k in body["kpis"]}
    assert kpis["silent"] == 1 and kpis["risk"] == 1

    disp = make_user("disp", "unit_dispatcher", tree["complex"])
    kpis = {k["key"]: k["value"] for k in _client(disp).get("/api/v1/analytics/workspace/").json()["kpis"]}
    assert kpis["new"] == 1


def test_workspace_respects_scope_and_role_choice(tree, make_user):
    _setup(tree)
    other = make_user("beta", "unit_dispatcher", tree["other"])
    kpis = {k["key"]: k["value"] for k in _client(other).get("/api/v1/analytics/workspace/").json()["kpis"]}
    assert kpis["new"] == 0 and kpis["risk"] == 0
    # чужую роль выбрать нельзя — остаётся своя
    body = _client(other).get("/api/v1/analytics/workspace/", {"role": "head"}).json()
    assert body["role"] == "unit_dispatcher"


def test_technician_sees_only_own_orders_and_no_incidents(tree, make_user):
    _, _, incident = _setup(tree)
    tech = make_user("tech", "technician", tree["complex"])
    mate = make_user("mate", "technician", tree["complex"])
    _order(tree, "WO-1", assignee=tech, status=WorkOrder.Status.IN_PROGRESS, incident=incident)
    _order(tree, "WO-2", assignee=mate, status=WorkOrder.Status.SUBMITTED)
    _order(tree, "WO-3", assignee=tech, status=WorkOrder.Status.DONE)
    _order(tree, "WO-4", assignee=tech, status=WorkOrder.Status.SUBMITTED, due=timedelta(hours=-1))

    body = _client(tech).get("/api/v1/analytics/workspace/").json()
    assert body["role"] == "technician"
    kpis = {k["key"]: k["value"] for k in body["kpis"]}
    assert kpis["mine"] == 2 and kpis["in_progress"] == 1 and kpis["overdue"] == 1
    assert [o["number"] for o in body["lists"]["my_orders"]] == ["WO-4", "WO-1"]

    scheme = _client(tech).get("/api/v1/analytics/scheme/", {"workorders": 1}).json()
    kinds = [f["properties"]["kind"] for f in scheme["features"]]
    assert "incident" not in kinds  # у бригады нет права видеть карточки
    orders = [f for f in scheme["features"] if f["properties"]["kind"] == "workorder"]
    assert {f["properties"]["number"] for f in orders} == {"WO-1", "WO-4"}
    # заявка по карточке стоит на пикете её каналов
    wo1 = next(f for f in orders if f["properties"]["number"] == "WO-1")
    assert wo1["geometry"]["coordinates"][0] == 12 and wo1["properties"]["mine"] is True
    assert next(f for f in orders if f["properties"]["number"] == "WO-4")["properties"]["overdue"] is True
    # и риск прогноза бригаде не показывается
    segments = [f["properties"] for f in scheme["features"] if f["properties"]["kind"] == "segment"]
    assert all(s["risk_level"] == "low" and s["health_avg"] is None for s in segments)


def test_scheme_cache_differs_by_role_in_one_scope(tree, make_user):
    _setup(tree)
    disp = make_user("disp", "unit_dispatcher", tree["complex"])
    tech = make_user("tech", "technician", tree["complex"])
    first = _client(disp).get("/api/v1/analytics/scheme/").json()
    assert any(f["properties"]["kind"] == "incident" for f in first["features"])
    # тот же объект, та же минута — но бригаде не достаётся схема диспетчера из кеша
    second = _client(tech).get("/api/v1/analytics/scheme/").json()
    assert not any(f["properties"]["kind"] == "incident" for f in second["features"])


def test_approved_order_goes_to_zone_brigade(tree, make_user):
    from apps.accounts.models import Team, TeamKind
    from apps.workorders import services as wo

    _, _, incident = _setup(tree)
    tech = make_user("tech", "technician", tree["complex"])
    head = make_user("head", "head", tree["district"])
    Team.objects.create(
        code="far", name="Бригада Беты", kind=TeamKind.BRIGADE, scope_node=tree["other"], lead=head
    )
    Team.objects.create(
        code="b1", name="Бригада Альфы", kind=TeamKind.BRIGADE, scope_node=tree["complex"], lead=tech
    )
    order = wo.draft_from_incident(incident, head)
    wo.transition(order, WorkOrder.Status.APPROVED, head)
    order.refresh_from_db()
    assert order.assignee == tech  # бригада той зоны, где объект, а не соседняя
    body = _client(tech).get("/api/v1/analytics/workspace/").json()
    assert [o["number"] for o in body["lists"]["my_orders"]] == [order.number]
