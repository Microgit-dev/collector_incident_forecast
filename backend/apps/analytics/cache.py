"""
Короткий кеш тяжёлых сводок по зоне ответственности. Схема и активные риски меняются не чаще цикла
прогноза (15 мин) и смен состояний; минута устаревания незаметна диспетчеру, а 20 одновременных
пользователей одной зоны не пересчитывают одно и то же.
"""

from __future__ import annotations

from collections.abc import Callable

from django.core.cache import cache

from apps.topology.selectors import has_global_scope, scope_paths

TTL = 60


def scope_key(user) -> str:
    """
    Зона ответственности и набор ролей: одна и та же зона выглядит по-разному для диспетчера
    и бригады (у бригады нет карточек и прогнозов), поэтому кеш у них разный.
    """
    # с учётом командирований: у командированного своя видимость
    scope = "all" if has_global_scope(user) else "|".join(scope_paths(user)) or "none"
    roles = "su" if user.is_superuser else ",".join(sorted(user.groups.values_list("name", flat=True)))
    return f"{scope}:{roles}"


def cached(name: str, user, params: tuple, build: Callable[[], dict], ttl: int = TTL) -> dict:
    key = f"analytics:{name}:{scope_key(user)}:" + ":".join(str(p) for p in params)
    value = cache.get(key)
    if value is None:
        value = build()
        cache.set(key, value, ttl)
    return value
