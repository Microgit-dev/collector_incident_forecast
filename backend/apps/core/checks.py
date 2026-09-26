"""
Проверки безопасности при старте (manage.py check, migrate, runserver): слабый SECRET_KEY и
демо-учётки. На стенде это предупреждения; в эксплуатации (DEMO_USERS=false) — ошибка, и сервис
не запустится с ключом по умолчанию.
"""

import os

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

WEAK_KEYS = {"dev-insecure-change-me", "change-me-please-long-random-string"}


def _production() -> bool:
    return os.environ.get("DEMO_USERS", "true").lower() not in {"1", "true", "yes"}


@register(Tags.security, deploy=False)
def secret_key_check(app_configs, **kwargs):
    key = settings.SECRET_KEY
    if key in WEAK_KEYS or len(key) < 50 or len(set(key)) < 5:
        cls = Error if _production() and not settings.DEBUG else Warning
        return [
            cls(
                "SECRET_KEY по умолчанию или слишком короткий: подписи сессий и сброса паролей можно подделать.",
                hint='Сгенерируйте ключ: python -c "import secrets; print(secrets.token_urlsafe(64))" и задайте в .env',
                id="collector.S001",
            )
        ]
    return []


@register(Tags.security, deploy=False)
def demo_users_check(app_configs, **kwargs):
    if not _production():
        return [
            Warning(
                "Включены демо-учётки с общим паролем (DEMO_USERS=true) — только для стенда.",
                hint="В эксплуатации: DEMO_USERS=false, пароль администратора и Grafana — сменить.",
                id="collector.S002",
            )
        ]
    return []
