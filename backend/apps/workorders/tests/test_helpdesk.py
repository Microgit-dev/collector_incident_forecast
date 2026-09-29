import httpx
import pytest

from apps.incidents import services as incident_services
from apps.incidents.models import Alert, IncidentEvent, IncidentType
from apps.workorders import services
from apps.workorders.models import WorkOrder


class FakeHelpdesk:
    """Help desk заказчика: заявка получает свой номер, статусы отдаются пачкой."""

    def __init__(self):
        self.tickets = {}

    def submit(self, payload):
        ticket = {"id": f"HD-{len(self.tickets) + 1:06d}", "status": "accepted", "status_label": "Принята"}
        self.tickets[ticket["id"]] = ticket
        return ticket

    def statuses(self, ids):
        return {i: self.tickets[i] for i in ids if i in self.tickets}


@pytest.fixture
def helpdesk(monkeypatch):
    fake = FakeHelpdesk()
    monkeypatch.setattr(services, "_client", lambda: fake)
    return fake


@pytest.fixture
def approved(tree, make_user):
    user = make_user("disp", "ods_dispatcher", tree["district"])
    incident = incident_services.raise_alert(
        type=IncidentType.FLOOD,
        severity="high",
        node=tree["house"],
        title="Затоплен",
        source=Alert.Source.RULE,
    ).incident
    order = services.draft_from_incident(incident, user)
    return services.transition(order, WorkOrder.Status.APPROVED, user), user


def test_submit_sends_to_helpdesk_and_sync_moves_forward(approved, helpdesk):
    order, user = approved
    order = services.transition(order, WorkOrder.Status.SUBMITTED, user)
    assert order.status == "submitted" and order.external_id == "HD-000001"

    helpdesk.tickets["HD-000001"] |= {
        "status": "in_progress",
        "status_label": "В работе",
        "assignee": "Бригада №2",
    }
    assert services.sync_external() == {"checked": 1, "changed": 1}
    order.refresh_from_db()
    assert order.status == "in_progress" and order.external_assignee == "Бригада №2"

    helpdesk.tickets["HD-000001"] |= {
        "status": "closed",
        "status_label": "Закрыта",
        "report": "Насосы обслужены",
    }
    services.sync_external()
    order.refresh_from_db()
    assert order.status == "done" and order.report == "Насосы обслужены"
    texts = list(
        order.incident.events.filter(kind=IncidentEvent.Kind.WORKORDER).values_list("text", flat=True)
    )
    assert any("выполнена: Насосы обслужены" in t for t in texts)
    # выполненная заявка больше не опрашивается
    assert services.sync_external() == {"checked": 0, "changed": 0}


def test_helpdesk_never_moves_order_back(approved, helpdesk):
    order, user = approved
    order = services.transition(order, WorkOrder.Status.SUBMITTED, user)
    WorkOrder.objects.filter(pk=order.pk).update(status=WorkOrder.Status.IN_PROGRESS)
    services.sync_external()  # в help desk всё ещё «Принята»
    order.refresh_from_db()
    assert order.status == "in_progress" and order.external_status == "Принята"


def test_unavailable_helpdesk_keeps_order_approved(approved, monkeypatch):
    order, user = approved

    class Down:
        def submit(self, payload):
            raise httpx.ConnectError("нет связи")

    monkeypatch.setattr(services, "_client", lambda: Down())
    with pytest.raises(services.WorkOrderError, match="недоступна"):
        services.transition(order, WorkOrder.Status.SUBMITTED, user)
    order.refresh_from_db()
    assert order.status == "approved" and order.external_id == ""


def test_without_helpdesk_brigade_takes_approved_order_directly(approved, monkeypatch):
    order, user = approved
    monkeypatch.setattr(services, "helpdesk_enabled", lambda: False)
    assert services.allowed(order) == {WorkOrder.Status.IN_PROGRESS, WorkOrder.Status.CANCELLED}
    services.transition(order, WorkOrder.Status.IN_PROGRESS, user)
    order.refresh_from_db()
    assert order.status == "in_progress"
    assert IncidentEvent.objects.filter(incident=order.incident, text__contains="бригада приступила").exists()


def test_with_helpdesk_approved_order_goes_through_it(approved, helpdesk):
    order, user = approved
    with pytest.raises(services.WorkOrderError, match="недопустим"):
        services.transition(order, WorkOrder.Status.IN_PROGRESS, user)
