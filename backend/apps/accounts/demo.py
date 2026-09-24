"""
Демо-состав для стенда: команды командной вертикали и сотрудники по ролям.

Совпадает с тестовым каталогом infra/ldap/bootstrap.ldif (логин, роль, departmentNumber = код
команды), поэтому вход работает и через LDAP, и локально, если LDAP выключен.
Зоны заданы названиями узлов из справочника объектов; если справочник ещё не загружен,
команды создаются без зоны и получают её при следующем запуске (после загрузки справочника).
"""

from dataclasses import dataclass

from django.contrib.auth.models import Group
from django.db import transaction

from apps.topology.models import Node

from .models import Team, TeamKind, User
from .roles import Role

DISTRICT = "Район по эксплуатации"


@dataclass(frozen=True)
class TeamSpec:
    code: str
    name: str
    kind: str
    scope: str | None  # название узла; None — корень района
    parent: str | None = None


@dataclass(frozen=True)
class PersonSpec:
    username: str
    last_name: str
    first_name: str
    role: Role
    team: str
    position: str
    lead: bool = False


TEAMS = [
    TeamSpec("management", "Руководство района", TeamKind.MANAGEMENT, DISTRICT),
    TeamSpec("ods", "ОДС района", TeamKind.ODS, DISTRICT, "management"),
    TeamSpec("analytics", "Аналитическая группа", TeamKind.ANALYTICS, DISTRICT, "management"),
    TeamSpec("support", "Администрирование и смежные службы", TeamKind.SUPPORT, DISTRICT, "management"),
    TeamSpec("unit-mu", "Диспетчерская объекта Мю", TeamKind.UNIT, "объект Мю", "ods"),
    TeamSpec("unit-ksi", "Диспетчерская объекта Кси", TeamKind.UNIT, "объект Кси", "ods"),
    TeamSpec("unit-tau", "Диспетчерская объекта Тау", TeamKind.UNIT, "объект Тау", "ods"),
    TeamSpec("brigade-mu", "Бригада № 1 (Мю)", TeamKind.BRIGADE, "объект Мю", "unit-mu"),
    TeamSpec("brigade-ksi", "Бригада № 2 (Кси)", TeamKind.BRIGADE, "объект Кси", "unit-ksi"),
    TeamSpec("brigade-tau", "Бригада № 3 (Тау)", TeamKind.BRIGADE, "объект Тау", "unit-tau"),
]

PEOPLE = [
    PersonSpec("head.sidorova", "Сидорова", "Мария", Role.HEAD, "management", "Начальник района", lead=True),
    PersonSpec(
        "ods.ivanov", "Иванов", "Иван", Role.ODS_DISPATCHER, "ods", "Старший диспетчер ОДС", lead=True
    ),
    PersonSpec("ods.kozlova", "Козлова", "Елена", Role.ODS_DISPATCHER, "ods", "Диспетчер ОДС"),
    PersonSpec(
        "analyst.kuznetsov", "Кузнецов", "Алексей", Role.ANALYST, "analytics", "Инженер-аналитик", lead=True
    ),
    PersonSpec(
        "admin.volkov", "Волков", "Дмитрий", Role.ADMIN, "support", "Администратор системы", lead=True
    ),
    PersonSpec("observer.orlova", "Орлова", "Анна", Role.OBSERVER, "support", "Инспектор смежной службы"),
    PersonSpec(
        "disp.petrov", "Петров", "Пётр", Role.UNIT_DISPATCHER, "unit-mu", "Диспетчер объекта", lead=True
    ),
    PersonSpec(
        "disp.nikolaev", "Николаев", "Олег", Role.UNIT_DISPATCHER, "unit-ksi", "Диспетчер объекта", lead=True
    ),
    PersonSpec(
        "disp.fedorova", "Фёдорова", "Ольга", Role.UNIT_DISPATCHER, "unit-tau", "Диспетчер объекта", lead=True
    ),
    PersonSpec("brigade.smirnov", "Смирнов", "Сергей", Role.TECHNICIAN, "brigade-mu", "Бригадир", lead=True),
    PersonSpec("brigade.popov", "Попов", "Андрей", Role.TECHNICIAN, "brigade-ksi", "Бригадир", lead=True),
    PersonSpec("brigade.egorov", "Егоров", "Николай", Role.TECHNICIAN, "brigade-tau", "Бригадир", lead=True),
]


def _node(name: str | None) -> Node | None:
    return Node.objects.filter(name=name).order_by("depth").first() if name else None


@transaction.atomic
def seed_demo(password: str) -> dict[str, int]:
    """Идемпотентно: команды обновляются по коду, сотрудники — по логину; пароль задаётся только новым."""
    teams: dict[str, Team] = {}
    for spec in TEAMS:
        team, _ = Team.objects.update_or_create(
            code=spec.code, defaults={"name": spec.name, "kind": spec.kind, "scope_node": _node(spec.scope)}
        )
        teams[spec.code] = team
    for spec in TEAMS:
        if spec.parent:
            Team.objects.filter(pk=teams[spec.code].pk).update(parent=teams[spec.parent])

    created = 0
    for spec in PEOPLE:
        team = teams[spec.team]
        user, is_new = User.objects.get_or_create(username=spec.username)
        user.last_name, user.first_name, user.position = spec.last_name, spec.first_name, spec.position
        user.email = f"{spec.username}@collector.local"
        user.team, user.scope_node = team, team.scope_node
        user.is_staff = spec.role == Role.ADMIN
        if is_new:
            user.set_password(password)
            created += 1
        user.save()
        user.groups.set([Group.objects.get(name=spec.role.value)])
        if spec.lead:
            Team.objects.filter(pk=team.pk).update(lead=user)
    return {"teams": len(teams), "users": len(PEOPLE), "created": created}


def attach_missing_scopes() -> int:
    """После загрузки справочника: демо-командам без зоны назначается зона по спецификации."""
    from .services import sync_team_scopes

    attached = 0
    for spec in TEAMS:
        node = _node(spec.scope)
        if node is not None:
            attached += Team.objects.filter(code=spec.code, scope_node=None).update(scope_node=node)
    if attached:
        sync_team_scopes()
    return attached
