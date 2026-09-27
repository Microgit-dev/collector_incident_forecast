"""
Единый контур пользователей: учебный контур не ведёт свои учётные записи, а зеркалирует основные.

Источник — база основной системы, подключённая к учебному контуру псевдонимом `identity` только на
чтение (IDENTITY_DATABASE_URL). Из неё берутся пользователи, их роли (группы по имени) и команды
(по коду). Своё у учебного контура — только зоны: команды полигона привязаны к объектам полигона,
поэтому участник команды получает зону команды полигона, а не боевую.

Синхронизация:
- при первом запросе пользователя с токеном основной системы (ensure_user) — сразу, без входа;
- периодически задачей sync_identity и при bootstrap — все учётки: новые, изменённые, заблокированные.
Пароли в учебный контур не копируются: входа там нет, токены выдаёт основная система.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.db import DatabaseError, transaction

from .models import Team, User

logger = logging.getLogger(__name__)

IDENTITY_DB = "identity"
CACHE_SECONDS = 60
# служебные учётки учебного контура, которых нет в основной системе
LOCAL_ACCOUNTS = {"training.bot"}
FIELDS = ("first_name", "last_name", "email", "position", "phone", "is_active", "is_superuser", "is_staff")


class IdentityRouter:
    """База основной системы только читается: миграции в неё из учебного контура не идут."""

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return False if db == IDENTITY_DB else None


def enabled() -> bool:
    return settings.CONTOUR != settings.IDENTITY_CONTOUR and IDENTITY_DB in settings.DATABASES


def _cache_key(username: str) -> str:
    return f"identity:user:{username}"


def _source():
    return User.objects.using(IDENTITY_DB).select_related("team", "team__parent", "team__scope_node")


def _local_team(source_team) -> Team | None:
    return sync_team(source_team) if source_team is not None else None


def sync_team(source_team) -> Team:
    """Команда по коду; зона — своя (полигон), для новой команды — узел с тем же названием, если есть."""
    from apps.topology.models import Node

    team = Team.objects.filter(code=source_team.code).first()
    if team is None:
        scope_name = source_team.scope_node.name if source_team.scope_node_id else None
        scope = Node.objects.filter(name=scope_name).order_by("depth").first() if scope_name else None
        team = Team(code=source_team.code, scope_node=scope)
    team.name, team.kind, team.is_active = source_team.name, source_team.kind, source_team.is_active
    team.save()
    return Team.objects.select_related("scope_node").get(pk=team.pk)


def apply(source: User, role_codes: list[str]) -> User:
    """Перенести учётку основной системы в учебный контур (идемпотентно)."""
    user = User.objects.filter(username=source.username).first() or User(username=source.username)
    for field in FIELDS:
        setattr(user, field, getattr(source, field))
    if user.pk is None or user.has_usable_password():
        user.set_unusable_password()
    team = _local_team(source.team)
    user.team = team
    if team is not None and team.scope_node_id:
        user.scope_node = team.scope_node
    user.save()
    user.groups.set(Group.objects.filter(name__in=role_codes))
    cache.set(_cache_key(user.username), user.pk, CACHE_SECONDS)
    return User.objects.get(pk=user.pk)  # сброс кеша прав


def ensure_user(username: str) -> User | None:
    """Учётка для запроса с токеном основной системы: из кеша или сразу из основной базы."""
    cached = cache.get(_cache_key(username))
    if cached:
        user = User.objects.filter(pk=cached).first()
        if user is not None:
            return user
    if not enabled():
        return User.objects.filter(username=username).first()
    try:
        return sync_user(username)
    except DatabaseError:
        # основная база недоступна — работаем по последней копии учётки
        logger.warning("identity database unavailable, using local copy of %s", username)
        return User.objects.filter(username=username, is_active=True).first()


@transaction.atomic
def sync_user(username: str) -> User | None:
    source = _source().filter(username=username).first()
    if source is None:
        User.objects.filter(username=username).exclude(username__in=LOCAL_ACCOUNTS).update(is_active=False)
        cache.delete(_cache_key(username))
        return None
    return apply(source, list(source.groups.values_list("name", flat=True)))


def sync_all() -> dict[str, int]:
    """Все команды и учётки основной системы; исчезнувшие там учётки блокируются здесь."""
    if not enabled():
        return {"skipped": 1}
    try:
        with transaction.atomic():
            teams = {}
            for source_team in Team.objects.using(IDENTITY_DB).select_related("scope_node"):
                teams[source_team.code] = sync_team(source_team)
            for source_team in Team.objects.using(IDENTITY_DB).select_related("parent"):
                parent = teams.get(source_team.parent.code) if source_team.parent_id else None
                Team.objects.filter(pk=teams[source_team.code].pk).update(parent=parent)
            names = set()
            for source in _source().prefetch_related("groups"):
                apply(source, [g.name for g in source.groups.all()])
                names.add(source.username)
            for source_team in Team.objects.using(IDENTITY_DB).exclude(lead=None).select_related("lead"):
                lead = User.objects.filter(username=source_team.lead.username).first()
                Team.objects.filter(pk=teams[source_team.code].pk).update(lead=lead)
            blocked = (
                User.objects.exclude(username__in=names | LOCAL_ACCOUNTS)
                .filter(is_active=True)
                .update(is_active=False)
            )
    except DatabaseError:
        logger.exception("identity sync failed")
        return {"error": 1}
    return {"teams": len(teams), "users": len(names), "blocked": blocked}
