from django.core.management.base import BaseCommand

from apps.forecasting.models import TrainingRun
from apps.forecasting.training import execute


class Command(BaseCommand):
    help = (
        "Обучение модели прогноза (отказ датчика, газ, подтопление) на всей истории с валидацией по времени"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--neg-rate", type=float, default=None, help="доля оставляемых отрицательных примеров"
        )
        parser.add_argument(
            "--activate", action="store_true", help="сделать активной даже при худшей валидации"
        )
        parser.add_argument("--horizon", type=int, default=24, help="горизонт прогноза, ч (кратно 24)")
        parser.add_argument("--task", default="sensor_failure", choices=["sensor_failure", "gas", "flood"])

    def handle(self, *args, neg_rate, activate, horizon, task, **options):
        params = {"activate": activate, "horizon_hours": horizon} | (
            {"neg_rate": neg_rate} if neg_rate else {}
        )
        run = TrainingRun.objects.create(task=task, params=params)
        model = execute(run, echo=self.stdout.write)
        m = model.metrics
        self.stdout.write(self.style.SUCCESS(f"model {model} [{model.status}]"))
        for part in ("valid", "test"):
            self.stdout.write(f"{part}: {m[part]}")
        self.stdout.write(f"baseline (test): {m['baseline_test']}")
        self.stdout.write(f"levels: {m['levels']}")
        for level, res in m["levels_test"].items():
            self.stdout.write(
                f"  {level}: P={res['precision']} R={res['recall']} alerts/day={res['alerts_per_day']}"
            )
        self.stdout.write(f"by type (test): {m['by_sensor_type_test']}")
        self.stdout.write(f"importance: {list(m['feature_importance'])[:10]}")
