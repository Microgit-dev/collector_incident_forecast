from django.core.management.base import BaseCommand

from apps.forecasting.models import ForecastTask, TrainingRun
from apps.forecasting.training import execute


class Command(BaseCommand):
    help = "Обучение модели отказа датчиков на всей истории (валидация по времени, метрики в реестре моделей)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--neg-rate", type=float, default=None, help="доля оставляемых отрицательных примеров"
        )
        parser.add_argument(
            "--activate", action="store_true", help="сделать активной даже при худшей валидации"
        )
        parser.add_argument("--horizon", type=int, default=24, help="горизонт прогноза, ч (кратно 24)")

    def handle(self, *args, neg_rate, activate, horizon, **options):
        params = {"activate": activate, "horizon_hours": horizon} | (
            {"neg_rate": neg_rate} if neg_rate else {}
        )
        run = TrainingRun.objects.create(task=ForecastTask.SENSOR_FAILURE, params=params)
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
