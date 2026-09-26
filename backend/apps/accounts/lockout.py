"""
Защита от подбора пароля: после LOCKOUT_ATTEMPTS неудачных попыток подряд учётная запись
блокируется на LOCKOUT_MINUTES. Работает для всех способов входа — JWT, админка, LDAP, — потому
что считает сигнал user_login_failed, а проверку делает первый бэкенд аутентификации.
Счётчик в Redis-кеше: общий для всех процессов и сам истекает; успешный вход его сбрасывает.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import cache
from django.core.exceptions import PermissionDenied

logger = logging.getLogger("security")


def _key(username: str) -> str:
    return f"login-fail:{(username or '').strip().lower()}"


def attempts(username: str) -> int:
    return cache.get(_key(username), 0)


def is_locked(username: str) -> bool:
    return attempts(username) >= settings.LOCKOUT_ATTEMPTS


def reset(username: str) -> None:
    cache.delete(_key(username))


def _failed(sender, credentials, request=None, **kwargs):
    username = credentials.get("username", "")
    key = _key(username)
    cache.add(key, 0, settings.LOCKOUT_MINUTES * 60)
    try:
        count = cache.incr(key)
    except ValueError:  # ключ истёк между add и incr
        cache.set(key, 1, settings.LOCKOUT_MINUTES * 60)
        count = 1
    if count == settings.LOCKOUT_ATTEMPTS:
        logger.warning("login locked: %s after %s failures", username, count)


def _succeeded(sender, user, request=None, **kwargs):
    reset(user.get_username())


def connect():
    user_login_failed.connect(_failed, dispatch_uid="lockout-failed")
    user_logged_in.connect(_succeeded, dispatch_uid="lockout-ok")


class LockoutBackend:
    """Первый в AUTHENTICATION_BACKENDS: заблокированную учётку дальше не пускает ни один бэкенд."""

    def authenticate(self, request, username=None, **kwargs):
        if username and is_locked(username):
            raise PermissionDenied  # цепочка бэкендов останавливается, вход не состоится
        return None

    def get_user(self, user_id):
        # сессия, созданная через этот бэкенд (force_login, первый в списке), должна находить пользователя
        from django.contrib.auth.backends import ModelBackend

        return ModelBackend().get_user(user_id)
