from django.core.checks import run_checks
from rest_framework.test import APIClient

URL = "/api/v1/auth/token/"


def test_lockout_after_five_failures_and_reset_on_success(make_user):
    make_user("petrov", "unit_dispatcher")
    client = APIClient()
    codes = [client.post(URL, {"username": "petrov", "password": f"bad{i}"}).status_code for i in range(5)]
    assert codes == [401] * 5
    locked = client.post(URL, {"username": "petrov", "password": "pass12345"})
    assert locked.status_code == 429 and "заблокирован" in locked.json()["detail"]
    # регистр логина не обходит блокировку
    assert client.post(URL, {"username": "PETROV", "password": "pass12345"}).status_code == 429


def test_success_resets_the_counter(make_user):
    make_user("petrov", "unit_dispatcher")
    client = APIClient()
    for i in range(4):
        client.post(URL, {"username": "petrov", "password": f"bad{i}"})
    assert client.post(URL, {"username": "petrov", "password": "pass12345"}).status_code == 200
    for i in range(4):
        client.post(URL, {"username": "petrov", "password": f"bad{i}"})
    assert client.post(URL, {"username": "petrov", "password": "pass12345"}).status_code == 200


def test_admin_login_is_locked_too(make_user, client, settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    make_user("petrov", "unit_dispatcher")
    for i in range(5):
        client.post("/admin/login/", {"username": "petrov", "password": f"bad{i}"})
    from apps.accounts.lockout import is_locked

    assert is_locked("petrov")


def test_logout_revokes_refresh_and_rotation(make_user):
    make_user("petrov", "unit_dispatcher")
    client = APIClient()
    tokens = client.post(URL, {"username": "petrov", "password": "pass12345"}).json()
    rotated = client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]}).json()
    assert rotated["refresh"] != tokens["refresh"]
    # старый refresh после ротации не работает
    assert client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]}).status_code == 401
    assert client.post("/api/v1/auth/logout/", {"refresh": rotated["refresh"]}).status_code == 204
    assert client.post("/api/v1/auth/token/refresh/", {"refresh": rotated["refresh"]}).status_code == 401


def test_api_schema_requires_login(make_user):
    assert APIClient().get("/api/schema/").status_code in (401, 403)
    client = APIClient()
    client.force_authenticate(make_user("petrov", "unit_dispatcher"))
    assert client.get("/api/schema/").status_code == 200


def test_weak_secret_key_is_an_error_in_production(settings, monkeypatch):
    settings.SECRET_KEY = "change-me-please-long-random-string"
    monkeypatch.setenv("DEMO_USERS", "true")
    ids = {m.id: m.level for m in run_checks(tags=["security"])}
    assert "collector.S001" in ids and "collector.S002" in ids
    monkeypatch.setenv("DEMO_USERS", "false")
    errors = [m for m in run_checks(tags=["security"]) if m.id == "collector.S001"]
    assert errors and errors[0].is_serious()


def test_unlock_command_lifts_the_lock(make_user):
    from django.core.management import call_command

    from apps.audit.models import ActionLog

    make_user("petrov", "unit_dispatcher")
    client = APIClient()
    for i in range(5):
        client.post(URL, {"username": "petrov", "password": f"bad{i}"})
    assert client.post(URL, {"username": "petrov", "password": "pass12345"}).status_code == 429
    call_command("unlock", "Petrov")
    assert client.post(URL, {"username": "petrov", "password": "pass12345"}).status_code == 200
    assert ActionLog.objects.filter(action="security.unlock").exists()
