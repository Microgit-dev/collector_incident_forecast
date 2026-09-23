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
