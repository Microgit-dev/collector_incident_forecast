from django.apps import AppConfig


class IncidentsConfig(AppConfig):
    name = "apps.incidents"
    label = "incidents"
    verbose_name = "Инциденты"

    def ready(self):
        from auditlog.registry import auditlog

        from . import rules  # noqa: F401 — подписка на сигналы телеметрии
        from .models import Decision, EscalationPolicy, Incident

        auditlog.register(Incident)
        auditlog.register(Decision)
        auditlog.register(EscalationPolicy)
