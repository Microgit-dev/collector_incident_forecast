from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

from apps.forecasting import services


class Command(BaseCommand):
    help = "Цикл прогноза (по умолчанию — на время последних данных) или бэктест по историческому периоду"

    def add_arguments(self, parser):
        parser.add_argument("--as-of", help="ISO-время, например 2026-06-15T12:00:00+03:00")
        parser.add_argument("--backtest", nargs=2, metavar=("FROM", "TO"), help="период бэктеста, ISO-время")
        parser.add_argument("--step-hours", type=int, default=24)

    def handle(self, *args, as_of=None, backtest=None, step_hours=24, **options):
        if backtest:
            start, end = (datetime.fromisoformat(v) for v in backtest)
            result = services.backtest(start, end, timedelta(hours=step_hours), echo=self.stdout.write)
            self.stdout.write(self.style.SUCCESS(str(result)))
            return
        moment = datetime.fromisoformat(as_of) if as_of else None
        self.stdout.write(str(services.run_cycle(moment)))
