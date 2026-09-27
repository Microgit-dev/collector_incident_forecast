"""Единая платформа: общий вход подсистем, админка без второго пароля, матрица ответственности."""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts import identity
from apps.accounts.models import Team, User
from apps.accounts.operations import OPERATIONS, operations_for
from apps.accounts.roles import Role


def _login(username: str) -> dict:
    response = APIClient().post("/api/v1/auth/token/", {"username": username, "password": "pass12345"})
    assert response.status_code == 200, response.content
    return response.json()


def _bearer(token: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_token_names_the_user_and_the_issuing_contour(make_user):
    make_user("petrov", "unit_dispatcher")
    tokens = _login("petrov")
    access = AccessToken(tokens["access"])
    assert access["username"] == "petrov" and access["ctr"] == "combat"
    me = _bearer(tokens["access"]).get("/api/v1/auth/me/")
    assert me.status_code == 200 and me.json()["contour"]["urls"]["training"] == "/training/"
    # обновление сохраняет контур: новый access так же принимается
    refreshed = APIClient().post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]}).json()
    assert AccessToken(refreshed["access"])["ctr"] == "combat"
    assert _bearer(refreshed["access"]).get("/api/v1/auth/me/").status_code == 200


def test_token_of_another_contour_is_rejected(make_user):
    user = make_user("petrov", "unit_dispatcher")
    forged = AccessToken.for_user(user)
    forged["ctr"] = "training"
    assert _bearer(str(forged)).get("/api/v1/auth/me/").status_code == 401
    legacy = AccessToken.for_user(user)  # старый токен без контура
    assert _bearer(str(legacy)).get("/api/v1/auth/me/").status_code == 401


def test_training_contour_takes_the_platform_token_and_has_no_login(make_user, settings):
    make_user("petrov", "unit_dispatcher")
    tokens = _login("petrov")
    settings.CONTOUR = "training"
    assert (
        APIClient().post("/api/v1/auth/token/", {"username": "petrov", "password": "pass12345"}).status_code
        == 403
    )
    assert APIClient().post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]}).status_code == 403
    me = _bearer(tokens["access"]).get("/api/v1/auth/me/")
    assert me.status_code == 200 and me.json()["contour"]["code"] == "training"


def test_identity_mirror_copies_roles_and_takes_the_local_team_zone(roles, tree):
    local_team = Team.objects.create(
        code="unit-mu", name="Диспетчерская Мю", kind="unit", scope_node=tree["complex"]
    )
    source_team = Team(code="unit-mu", name="Диспетчерская объекта Мю", kind="unit", is_active=True)
    source = User(
        username="new.person", first_name="Ольга", last_name="Новикова", is_active=True, team=source_team
    )
    user = identity.apply(source, ["unit_dispatcher"])
    assert user.role_codes == ["unit_dispatcher"] and user.team == local_team
    assert user.scope_node == tree["complex"]  # зона — полигона, а не боевая
    assert not user.has_usable_password()  # входа в учебный контур нет
    local_team.refresh_from_db()
    assert local_team.name == "Диспетчерская объекта Мю"
    blocked = User(username="new.person", is_active=False, team=None)
    assert not identity.apply(blocked, []).is_active


def test_admin_session_opens_the_admin_without_a_second_password(make_user, settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    make_user("kuznetsov", "analyst")
    client = _bearer(_login("kuznetsov")["access"])
    opened = client.post("/api/v1/auth/admin-session/")
    assert opened.status_code == 200 and opened.json()["url"] == "/admin/"
    page = client.get("/admin/")
    assert page.status_code == 200
    html = page.content.decode()
    assert "Ваши задачи" in html and "Датчики и контракты данных" in html
    assert "Пользователи и роли" not in html  # не его раздел
    client.delete("/api/v1/auth/admin-session/")
    assert client.get("/admin/").status_code == 302


def test_admin_is_closed_to_roles_without_operations_and_login_goes_to_the_platform(
    make_user, client, settings
):
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    make_user("smirnov", "technician")
    assert _bearer(_login("smirnov")["access"]).post("/api/v1/auth/admin-session/").status_code == 403
    response = client.get("/admin/login/?next=/admin/wiki/")
    assert response.status_code == 302 and response["Location"] == "/login?next=/admin/wiki/"
    assert client.get("/admin/login/?direct=1").status_code == 200  # резервный вход администратора
    # в подсистеме /training/ возврат — в её админку, а не в админку основной системы
    settings.FORCE_SCRIPT_NAME = "/training"
    response = client.get("/admin/login/?next=/admin/")
    assert response["Location"] == "/login?next=/training/admin/"


@pytest.mark.parametrize("role", list(Role))
def test_every_role_gets_exactly_its_operations(make_user, role):
    user = make_user(f"u-{role.value}", role.value)
    expected = {op.code for op in OPERATIONS if role in op.roles or role == Role.ADMIN}
    assert {op.code for op in operations_for(user)} == expected


def test_operations_endpoint_is_open_to_everyone(make_user):
    make_user("orlova", "observer")
    body = _bearer(_login("orlova")["access"]).get("/api/v1/auth/operations/").json()
    assert body["mine"] == [] and len(body["matrix"]) == len(OPERATIONS)
    assert body["roles"]["head"] == "Руководитель подразделения"
