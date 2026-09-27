from django.core.management.base import BaseCommand

from apps.forecasting.indicator_calibration import available_years, calibrate


class Command(BaseCommand):
    help = (
        "Калибровка индекса пожара и НСД в вероятность по Parquet-архиву: обучение на годах до "
        "отложенного, проверка на отложенном (по умолчанию — последний год архива)"
    )

    def add_arguments(self, parser):
        parser.add_argument("--years", nargs="*", type=int, help="годы архива (по умолчанию все, кроме 2021)")
        parser.add_argument("--test-year", type=int, help="отложенный год для проверки")

    def handle(self, *args, years=None, test_year=None, **options):
        years = years or available_years()
        if not years:
            self.stdout.write("архив пуст: сначала загрузите журналы (раздел «Загрузка данных»)")
            return
        result = calibrate(years, test_year, progress=self.stdout.write)
        for row in result.values():
            c, t = row.calibration, row.test
            self.stdout.write(
                self.style.SUCCESS(
                    f"{row.get_task_display()}: {row.period}, случаев {c['n']}, проявилось {c['k']} "
                    f"(частота {c['base_rate']:.1%})"
                )
            )
            for b in c["bins"]:
                self.stdout.write(f"  индекс {b['lo']:.2f}–{b['hi']:.2f}: n={b['n']:>6} → {b['p']:.1%}")
            if t:
                self.stdout.write(
                    f"  проверка {row.test_period}: n={t['n']}, Brier {t['brier']} "
                    f"(частота {t['brier_base']}, индекс как вероятность {t['brier_index']})"
                )
