import re

import polars as pl
from django.core.management.base import BaseCommand

from apps.ingestion import archive, history


class Command(BaseCommand):
    help = "Пересобирает суточную витрину из нормализованного архива Parquet (без повторного чтения CSV)"

    def add_arguments(self, parser):
        parser.add_argument("--years", nargs="*", type=int, help="по умолчанию — все годы архива")

    def handle(self, *args, years=None, **options):
        for path in sorted(history.archive_dir().glob("journal_*.parquet")):
            year = int(re.search(r"(\d{4})", path.name).group(1))
            if years and year not in years:
                continue
            frame = archive.daily_frame(
                pl.scan_parquet(path), progress=lambda f, s, y=year: self.stdout.write(f"[{y}] {f:5.0%} {s}")
            )
            self.stdout.write(self.style.SUCCESS(f"[{year}] daily rows: {archive.load_daily(frame)}"))
