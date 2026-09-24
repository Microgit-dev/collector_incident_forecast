from datetime import date

from django.core.management.base import BaseCommand

from apps.integrations import weather


class Command(BaseCommand):
    help = "Погода по Москве из Open-Meteo: архив за период и/или последние сутки с прогнозом"

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="start", type=date.fromisoformat)
        parser.add_argument("--to", dest="end", type=date.fromisoformat)
        parser.add_argument("--recent", action="store_true", help="последние 10 суток и прогноз на 3")

    def handle(self, *args, start=None, end=None, recent=False, **options):
        if start and end:
            self.stdout.write(f"архив: {weather.load_history(start, end)} суток")
        if recent:
            self.stdout.write(f"последние и прогноз: {weather.sync_recent()} суток")
