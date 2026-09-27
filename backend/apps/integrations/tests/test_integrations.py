"""Интеграции: реестр оборудования (файл/API), help desk с картой статусов, камеры, страница интеграций."""

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.assets.models import Camera, Channel, Equipment
from apps.assets.registry_sync import apply, read_file


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


CSV = (
    "inventory_number;name;kind;object;picket;last_maintenance_at;maintenance_interval_days;channel_ids\n"
    "НС-1;Насос АНС-1;Насос;Объект Альфа;12,5;01.03.2026;90;501\n"
    "ВН-1;Вентилятор ВШ-2;fan;ДП Альфа;;2026-01-10;180;\n"
    "ЛК-1;Люк;неизвестно;Объект Альфа;;;;\n"
    "ЛК-2;Люк 2;hatch;Нет такого объекта;;;;\n"
).encode("cp1251")


def test_registry_file_import_creates_updates_retires(tree):
    Channel.objects.create(external_id=501, node=tree["house"], name="Насос АНС-1")
    Equipment.objects.create(kind="pump", node=tree["house"], name="Эмуляция", source="emulated")
    Equipment.objects.create(
        kind="fan", node=tree["house"], name="Старый", inventory_number="СТ-1", source="imported"
    )
    Equipment.objects.create(
        kind="door", node=tree["house"], name="Ручная", inventory_number="РЧ-1", source="manual"
    )

    result = apply(read_file("registry.csv", CSV))
    assert result["created"] == 2 and result["error_count"] == 2
    assert {e["inventory_number"] for e in result["errors"]} == {"ЛК-1", "ЛК-2"}
    pump = Equipment.objects.get(inventory_number="НС-1")
    assert pump.kind == "pump" and pump.source == "imported" and pump.picket == Decimal("12.5")
    assert pump.next_maintenance_at.isoformat() == "2026-05-30"
    assert list(pump.channels.values_list("external_id", flat=True)) == [501]
    # эмуляция заменена реестром, пропавшая из реестра единица выведена, ручная не тронута
    assert not Equipment.objects.filter(source="emulated").exists()
    assert Equipment.objects.get(inventory_number="СТ-1").is_active is False
    assert Equipment.objects.get(inventory_number="РЧ-1").is_active is True

    # повторная выгрузка с более ранней датой ТО не откатывает ТО, отмеченное в системе
    pump.last_maintenance_at = pump.last_maintenance_at.replace(month=6)
    pump.save()
    apply(read_file("registry.csv", CSV))
    assert Equipment.objects.get(inventory_number="НС-1").last_maintenance_at.month == 6


def test_registry_import_endpoint_and_template(tree, make_user):
    engineer = make_user("eng", "maintenance_engineer", tree["district"])
    client = _client(engineer)
    assert client.get("/api/v1/integrations/registry/import/").status_code == 200
    upload = SimpleUploadedFile("r.csv", CSV, content_type="text/csv")
    response = client.post("/api/v1/integrations/registry/import/", {"file": upload}, format="multipart")
    assert response.status_code == 200 and response.json()["created"] == 2
    disp = make_user("disp", "unit_dispatcher", tree["district"])
    assert (
        _client(disp).post("/api/v1/integrations/registry/import/", {}, format="multipart").status_code == 403
    )


def test_registry_api_pages(tree, monkeypatch):
    from apps.integrations import clients

    pages = {
        "http://reg/api/": {
            "results": [{"inventory_number": "А-1", "name": "Насос", "kind": "pump", "object": "ДП Альфа"}],
            "next": "http://reg/api/?p=2",
        },
        "http://reg/api/?p=2": {
            "results": [{"inventory_number": "А-2", "name": "ИБП", "kind": "ups", "object": "ДП Альфа"}],
            "next": None,
        },
    }

    class Response:
        def __init__(self, url):
            self.data = pages[url]

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    monkeypatch.setattr(clients.httpx, "get", lambda url, **kw: Response(url))
    rows = clients.RegistryClient("http://reg/api/").rows()
    assert [r["inventory_number"] for r in rows] == ["А-1", "А-2"]


def test_helpdesk_status_map_and_off_mode(settings, tree):
    from apps.workorders import services

    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "HELPDESK_STATUS_MAP": {"Исполнено": "done"}}
    assert services.external_status("Исполнено") == "done"
    assert services.external_status("in_progress") == "in_progress"  # статусы эмулятора остаются
    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "HELPDESK_MODE": "off"}
    assert services.sync_external()["checked"] == 0


def test_integrations_page_admin_only(tree, make_user, monkeypatch):
    from apps.integrations import registry

    admin = make_user("admin", "admin", tree["district"])
    rows = _client(admin).get("/api/v1/integrations/").json()
    assert {r["code"] for r in rows} >= {"smvu", "ldap", "helpdesk", "registry", "vms", "weather"}
    helpdesk = next(r for r in rows if r["code"] == "helpdesk")
    assert helpdesk["emulated"] is True and helpdesk["mode"] == "mock"

    # проверка упала — ошибка видна администратору в списке
    broken = registry.Integration(**{**registry.BY_CODE["vms"].__dict__, "check": lambda: 1 / 0})
    monkeypatch.setitem(registry.BY_CODE, "vms", broken)
    result = _client(admin).post("/api/v1/integrations/vms/check/").json()
    assert result["ok"] is False and "ZeroDivisionError" in result["error"]
    row = next(r for r in _client(admin).get("/api/v1/integrations/").json() if r["code"] == "vms")
    assert row["last_error"].startswith("ZeroDivisionError")

    analyst = make_user("analyst", "analyst", tree["district"])
    assert _client(analyst).get("/api/v1/integrations/").status_code == 403


@pytest.fixture
def cameras(tree):
    near = Camera.objects.create(
        node=tree["house"], name="Камера ПК12", external_id="C-12", picket=Decimal(12)
    )
    far = Camera.objects.create(
        node=tree["house"], name="Камера ПК40", external_id="C-40", picket=Decimal(40)
    )
    other = Camera.objects.create(node=tree["other"], name="Чужая", external_id="C-X", picket=Decimal(12))
    return near, far, other


def test_nearest_cameras_to_alarm(tree, cameras, make_user):
    from apps.incidents import services
    from apps.incidents.models import Alert, IncidentType

    channel = Channel.objects.create(external_id=7, node=tree["house"], name="Дым ПК38", picket=Decimal(38))
    incident = services.raise_alert(
        type=IncidentType.FIRE,
        severity="high",
        node=tree["house"],
        channel=channel,
        title="Дым",
        source=Alert.Source.RULE,
    ).incident
    disp = make_user("disp", "unit_dispatcher", tree["complex"])
    body = _client(disp).get("/api/v1/integrations/cameras/", {"incident": incident.pk}).json()
    assert [c["name"] for c in body["cameras"]] == ["Камера ПК40", "Камера ПК12"]
    assert body["cameras"][0]["distance"] == 2.0
    assert body["cameras"][0]["live_url"].startswith("/vms/live/C-40")


def test_snapshot_proxied_and_recorded_once(tree, cameras, make_user, monkeypatch):
    from apps.incidents import services
    from apps.incidents.models import Alert, IncidentEvent, IncidentType
    from apps.integrations import clients

    calls = []

    def fake_snapshot(self, camera_id, at=None):
        calls.append((camera_id, at))
        return b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"

    monkeypatch.setattr(clients.VideoClient, "snapshot", fake_snapshot)
    incident = services.raise_alert(
        type=IncidentType.INTRUSION,
        severity="high",
        node=tree["house"],
        title="Люк",
        source=Alert.Source.RULE,
    ).incident
    near = cameras[0]
    client = _client(make_user("disp", "unit_dispatcher", tree["complex"]))
    url = f"/api/v1/integrations/cameras/{near.pk}/snapshot/"
    for _ in range(2):
        response = client.get(url, {"incident": incident.pk, "at": "2026-06-24T12:30:00+03:00"})
        assert response.status_code == 200 and response["Content-Type"] == "image/svg+xml"
        assert "default-src 'none'" in response["Content-Security-Policy"]
    assert calls[0] == ("C-12", "2026-06-24T12:30:00+03:00")
    events = IncidentEvent.objects.filter(incident=incident, kind=IncidentEvent.Kind.VIDEO_CHECK)
    assert events.count() == 1 and "Камера ПК12" in events.get().text

    # камера чужой зоны недоступна
    other = cameras[2]
    assert client.get(f"/api/v1/integrations/cameras/{other.pk}/snapshot/").status_code == 404


def test_snapshot_rejects_non_image(tree, cameras, make_user, monkeypatch):
    from apps.integrations import clients

    monkeypatch.setattr(clients.VideoClient, "snapshot", lambda self, cid, at=None: (b"<html>", "text/html"))
    client = _client(make_user("disp", "unit_dispatcher", tree["complex"]))
    assert client.get(f"/api/v1/integrations/cameras/{cameras[0].pk}/snapshot/").status_code == 502
