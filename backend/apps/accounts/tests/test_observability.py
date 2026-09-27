"""Вход в Grafana и Prometheus через учётную запись системы (Caddy forward_auth)."""

from django.core import signing
from django.test import Client
from rest_framework.test import APIClient

from apps.accounts.observability import COOKIE, SALT

AUTH = "/api/v1/observability/auth/"
SESSION = "/api/v1/observability/session/"


def _session(user) -> str:
    client = APIClient()
    client.force_authenticate(user)
    response = client.post(SESSION)
    assert response.status_code == 200, response.content
    return response.cookies[COOKIE].value


def _auth(cookie: str | None, service: str):
    client = Client()
    if cookie:
        client.cookies[COOKIE] = cookie
    return client.get(AUTH, {"service": service})


def test_analyst_gets_grafana_viewer_but_not_prometheus(make_user):
    analyst = make_user("analyst", "analyst")
    cookie = _session(analyst)
    response = _auth(cookie, "grafana")
    assert response.status_code == 200
    assert response["X-WEBAUTH-USER"] == "analyst"
    assert response["X-WEBAUTH-ROLE"] == "Viewer"
    assert _auth(cookie, "prometheus").status_code == 403


def test_admin_gets_grafana_admin_and_prometheus(make_user):
    admin = make_user("admin", "admin")
    cookie = _session(admin)
    assert _auth(cookie, "grafana")["X-WEBAUTH-ROLE"] == "Admin"
    assert _auth(cookie, "prometheus").status_code == 200


def test_dispatcher_has_no_observability(make_user):
    disp = make_user("disp", "unit_dispatcher")
    client = APIClient()
    client.force_authenticate(disp)
    assert client.post(SESSION).status_code == 403
    assert client.get(SESSION).json()["grafana"] is None


def test_missing_forged_or_revoked_cookie_is_rejected(make_user):
    assert _auth(None, "grafana").status_code == 401
    # подпись другим ключом (подделка) не принимается
    forged = signing.TimestampSigner(key="other-key", salt=SALT).sign("1")
    assert _auth(forged, "grafana").status_code == 401
    analyst = make_user("analyst", "analyst")
    cookie = _session(analyst)
    analyst.is_active = False
    analyst.save()
    from django.core.cache import cache

    cache.clear()  # проверка кешируется на 30 с — блокировка учётки действует после сброса кеша
    assert _auth(cookie, "grafana").status_code == 401


def test_logout_deletes_cookie(make_user):
    client = APIClient()
    client.force_authenticate(make_user("analyst", "analyst"))
    client.post(SESSION)
    response = client.delete(SESSION)
    assert response.status_code == 204
    assert response.cookies[COOKIE].value == ""
