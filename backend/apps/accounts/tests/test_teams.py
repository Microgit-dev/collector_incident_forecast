import pytest
from rest_framework.test import APIClient

from apps.accounts import demo
from apps.accounts.models import Team, TeamKind, User
from apps.accounts.services import apply_directory_attrs, sync_team_scopes
from apps.topology.models import Node, NodeKind


@pytest.fixture
def district(db):
    root = Node.objects.add_root(create_kwargs={"name": demo.DISTRICT, "kind": NodeKind.DISTRICT})
    for name in ("объект Мю", "объект Кси", "объект Тау"):
        Node.objects.add_child(Node.objects.get(pk=root.pk), {"name": name, "kind": NodeKind.COMPLEX})
    return Node.objects.get(pk=root.pk)


def test_seed_builds_command_vertical(district, roles):
    result = demo.seed_demo("Passw0rd!")
    assert result == {"teams": len(demo.TEAMS), "users": len(demo.PEOPLE), "created": len(demo.PEOPLE)}

    brigade = Team.objects.get(code="brigade-mu")
    assert [t.code for t in brigade.chain()] == ["brigade-mu", "unit-mu", "ods", "management"]
    petrov = User.objects.get(username="disp.petrov")
    assert petrov.scope_node.name == "объект Мю"
    assert petrov.role_codes == ["unit_dispatcher"]
    assert Team.objects.get(code="unit-mu").lead == petrov
    assert petrov.check_password("Passw0rd!")

    # повторный запуск идемпотентен и не меняет пароль, заданный пользователем
    petrov.set_password("changed-123")
    petrov.save()
    assert demo.seed_demo("Passw0rd!")["created"] == 0
    assert User.objects.get(username="disp.petrov").check_password("changed-123")


def test_scopes_attach_after_reference_arrives(db, roles):
    demo.seed_demo("Passw0rd!")
    assert User.objects.get(username="disp.petrov").scope_node is None

    root = Node.objects.add_root(create_kwargs={"name": demo.DISTRICT, "kind": NodeKind.DISTRICT})
    Node.objects.add_child(root, {"name": "объект Мю", "kind": NodeKind.COMPLEX})
    assert demo.attach_missing_scopes() >= 2
    assert User.objects.get(username="disp.petrov").scope_node.name == "объект Мю"


def test_directory_department_assigns_team_and_scope(tree):
    team = Team.objects.create(
        code="unit-alpha", name="ДП Альфа", kind=TeamKind.UNIT, scope_node=tree["complex"]
    )
    user = User(username="new.user")
    apply_directory_attrs(user, {"departmentnumber": ["unit-alpha"], "title": ["Диспетчер"]})
    assert user.team == team and user.scope_node == tree["complex"] and user.position == "Диспетчер"

    # неизвестный код не сбрасывает назначенную вручную команду
    apply_directory_attrs(user, {"departmentnumber": ["nope"]})
    assert user.team == team


def test_team_scope_change_propagates_to_members(tree, make_user):
    team = Team.objects.create(code="t", name="T", kind=TeamKind.UNIT, scope_node=tree["house"])
    user = make_user("u", "unit_dispatcher", tree["house"])
    user.team = team
    user.save()
    team.scope_node = tree["other"]
    team.save()
    assert sync_team_scopes() == 1
    assert User.objects.get(pk=user.pk).scope_node == tree["other"]


def test_teams_api_and_me_expose_chain(district, roles):
    demo.seed_demo("Passw0rd!")
    client = APIClient()
    client.force_authenticate(User.objects.get(username="brigade.smirnov"))
    me = client.get("/api/v1/auth/me/").json()
    assert me["team"]["code"] == "brigade-mu"
    assert [t["code"] for t in me["command_chain"]] == ["unit-mu", "ods", "management"]
    teams = client.get("/api/v1/teams/").json()
    assert {t["code"] for t in teams} == {t.code for t in demo.TEAMS}
