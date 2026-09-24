import json
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.services import sync_roles
from apps.forecasting.models import ForecastTask, RiskLevel, RiskPolicy
from apps.incidents.models import DecisionOutcome, DecisionReason, EscalationPolicy
from apps.normalization.services import seed_default_taxonomy

ESCALATION = {
    RiskLevel.CRITICAL: (5, 3, 2),
    RiskLevel.HIGH: (15, 3, 5),
    RiskLevel.MEDIUM: (60, 2, 15),
    RiskLevel.LOW: (240, 1, 60),
}

REASONS = [
    ("false-sensor-fault", "Ложное срабатывание: неисправность датчика", DecisionOutcome.FALSE_ALARM),
    (
        "false-maintenance",
        "Ложное срабатывание: плановые / профилактические работы",
        DecisionOutcome.FALSE_ALARM,
    ),
    (
        "false-authorized-access",
        "Ложное срабатывание: санкционированный доступ (наряд-допуск)",
        DecisionOutcome.FALSE_ALARM,
    ),
    (
        "false-environment",
        "Ложное срабатывание: внешнее воздействие (нагрев, конденсат, пыль)",
        DecisionOutcome.FALSE_ALARM,
    ),
    (
        "false-power-glitch",
        "Ложное срабатывание: кратковременный сбой питания / связи",
        DecisionOutcome.FALSE_ALARM,
    ),
    ("brigade-fire", "Выезд бригады: признаки возгорания / задымления", DecisionOutcome.BRIGADE_DISPATCHED),
    ("brigade-flood", "Выезд бригады: угроза подтопления", DecisionOutcome.BRIGADE_DISPATCHED),
    ("brigade-intrusion", "Выезд бригады: признаки проникновения", DecisionOutcome.BRIGADE_DISPATCHED),
    ("brigade-equipment", "Выезд бригады: отказ оборудования", DecisionOutcome.BRIGADE_DISPATCHED),
    ("check-video", "Проверка по камерам видеонаблюдения", DecisionOutcome.CHECK_REQUESTED),
    ("check-patrol", "Проверка обходчиком", DecisionOutcome.CHECK_REQUESTED),
    ("monitor-trend", "Наблюдение за динамикой показаний", DecisionOutcome.MONITORING),
    ("monitor-weather", "Наблюдение: ожидаются осадки / оттепель", DecisionOutcome.MONITORING),
    ("confirmed", "Инцидент подтверждён", DecisionOutcome.CONFIRMED),
    ("resolved-onsite", "Устранено на месте", DecisionOutcome.RESOLVED),
    ("resolved-remote", "Устранено дистанционно (перезапуск, переключение)", DecisionOutcome.RESOLVED),
]

PERIODIC = [
    # (name, task, seconds)
    ("Эскалация инцидентов без реакции", "apps.incidents.tasks.escalate_overdue_incidents", 60),
    ("Цикл прогнозирования", "apps.forecasting.tasks.run_forecast_cycle", 900),
    ("Суточная витрина телеметрии", "apps.telemetry.tasks.rollup_daily", 3600),
]


class Command(BaseCommand):
    help = "Идемпотентная инициализация: роли, таксономия состояний, политики, справочники, расписания"

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(f"roles: {sync_roles()}")
        self.stdout.write(f"taxonomy: {seed_default_taxonomy()}")

        for severity, (minutes, levels, repeat) in ESCALATION.items():
            EscalationPolicy.objects.get_or_create(
                severity=severity,
                defaults={
                    "ack_timeout_minutes": minutes,
                    "max_level": levels,
                    "repeat_notify_minutes": repeat,
                },
            )
        for task in ForecastTask.values:
            RiskPolicy.objects.get_or_create(task=task)
        for code, name, outcome in REASONS:
            DecisionReason.objects.get_or_create(code=code, defaults={"name": name, "outcome": outcome})
        self._schedules()
        self._reference()
        self._demo()
        self._superuser()
        self.stdout.write(self.style.SUCCESS("bootstrap done"))

    def _schedules(self):
        from django_celery_beat.models import IntervalSchedule, PeriodicTask

        for name, task, seconds in PERIODIC:
            interval, _ = IntervalSchedule.objects.get_or_create(
                every=seconds, period=IntervalSchedule.SECONDS
            )
            PeriodicTask.objects.get_or_create(
                name=name, defaults={"task": task, "interval": interval, "kwargs": json.dumps({})}
            )

    def _reference(self):
        """Справочники заказчика, если каталог данных смонтирован (идемпотентно)."""
        from django.conf import settings

        from apps.assets.models import Equipment
        from apps.assets.registry import emulate_registry
        from apps.assets.services import import_channels
        from apps.topology.services import import_objects

        base = settings.DATA_DIR / "dataset"
        objects, channels = (
            base / "справочник_объектов_диспетчер.csv",
            base / "справочник_каналов_датчиков.csv",
        )
        if not (objects.exists() and channels.exists()):
            self.stdout.write("reference: data dir not mounted, skipped")
            return
        self.stdout.write(f"objects: {import_objects(objects)}")
        self.stdout.write(f"channels: {import_channels(channels)}")
        if not Equipment.objects.exists():
            self.stdout.write(f"equipment: {emulate_registry()}")

    def _demo(self):
        """Демо-команды и сотрудники: включены по умолчанию для стенда, в эксплуатации DEMO_USERS=false."""
        if os.environ.get("DEMO_USERS", "true").lower() not in {"1", "true", "yes"}:
            return
        from apps.accounts.demo import seed_demo

        self.stdout.write(f"demo: {seed_demo(os.environ.get('DEMO_PASSWORD', 'Passw0rd!'))}")

    def _superuser(self):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        if not username or not password:
            return
        User = get_user_model()
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, password=password, email="")
            self.stdout.write(f"superuser {username} created")
