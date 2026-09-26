from django.apps import AppConfig


class WikiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.wiki"
    verbose_name = "Вики для сотрудников"

    def ready(self):
        from auditlog.registry import auditlog

        from .models import WikiPage

        auditlog.register(WikiPage)  # история правок: кто и что поменял в статье
