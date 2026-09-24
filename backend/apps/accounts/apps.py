from django.apps import AppConfig
from django.conf import settings


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Пользователи и роли"

    def ready(self):
        if getattr(settings, "AUTH_LDAP_SERVER_URI", None):
            from .ldap import connect_signals

            connect_signals()
