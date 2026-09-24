import fnmatch
import logging

from django.contrib.auth.models import Group, Permission
from django.db import transaction

from .roles import ROLES

logger = logging.getLogger(__name__)


def _resolve(patterns: list[str], all_perms: list[Permission]) -> set[Permission]:
    resolved: set[Permission] = set()
    for pattern in patterns:
        matched = [
            p for p in all_perms if fnmatch.fnmatchcase(f"{p.content_type.app_label}.{p.codename}", pattern)
        ]
        if not matched:
            logger.warning("role permission pattern %r matched nothing", pattern)
        resolved.update(matched)
    return resolved


@transaction.atomic
def sync_roles() -> dict[str, int]:
    """Создаёт/обновляет группы-роли по roles.ROLES. Идемпотентна, вызывается при bootstrap."""
    all_perms = list(Permission.objects.select_related("content_type"))
    result = {}
    for role, spec in ROLES.items():
        group, _ = Group.objects.get_or_create(name=role.value)
        perms = _resolve(spec.perms, all_perms)
        group.permissions.set(perms)
        result[role.value] = len(perms)
    return result


def assign_team(user, team) -> None:
    """Участник команды получает её зону ответственности."""
    user.team = team
    user.scope_node = team.scope_node if team else user.scope_node
    user.save(update_fields=["team", "scope_node"])


def sync_team_scopes() -> int:
    """Выравнивает зоны участников по зонам их команд (после смены зоны команды или справочника)."""
    from .models import Team, User

    changed = 0
    for team in Team.objects.exclude(scope_node=None):
        changed += (
            User.objects.filter(team=team)
            .exclude(scope_node=team.scope_node)
            .update(scope_node=team.scope_node)
        )
    return changed


def apply_directory_attrs(user, attrs: dict[str, list[str]]) -> None:
    """
    Атрибуты учётки из LDAP/AD → команда, зона ответственности и должность.
    Код команды берётся из departmentNumber (в AD обычно department). Неизвестный код
    не сбрасывает текущую команду: её могли назначить вручную в админке.
    """
    from .models import Team

    def first(*names):
        for name in names:
            if values := attrs.get(name.lower()):
                return values[0]
        return ""

    if title := first("title"):
        user.position = title
    if phone := first("telephoneNumber", "mobile"):
        user.phone = phone
    code = first("departmentNumber", "department")
    team = (
        Team.objects.filter(code=code, is_active=True).select_related("scope_node").first() if code else None
    )
    if team:
        user.team = team
        user.scope_node = team.scope_node
