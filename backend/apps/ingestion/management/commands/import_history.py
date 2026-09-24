import json
import re
import time
from pathlib import Path

import polars as pl
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.ingestion import archive
from apps.ingestion.models import DataSource, ImportJob

# 2021: всплеск тревог из-за перехода на новую систему мониторинга — заказчик рекомендует исключить
DEFAULT_EXCLUDED = [2021]


class Command(BaseCommand):
    help = (
        "Импорт исторических журналов СМВУ: нормализация в Parquet-архив, отчёт о качестве, "
        "суточная витрина за всю историю и сырые показания за оперативное окно в hypertable"
    )

    def add_arguments(self, parser):
        parser.add_argument("--journals", default=str(settings.DATA_DIR / "dataset" / "journals"))
        parser.add_argument("--years", type=int, nargs="*", help="По умолчанию — все найденные файлы")
        parser.add_argument("--exclude", type=int, nargs="*", default=DEFAULT_EXCLUDED)
        parser.add_argument("--raw-days", type=int, default=30, help="Оперативное окно сырых показаний, дней")
        parser.add_argument(
            "--reuse-parquet", action="store_true", help="Не пересобирать уже готовый Parquet"
        )
        parser.add_argument("--no-db", action="store_true", help="Только Parquet и отчёт, без загрузки в БД")

    def handle(self, *args, journals, years, exclude, raw_days, reuse_parquet, no_db, **options):
        out_dir = settings.ARTIFACTS_DIR / "archive"
        files = {
            int(m.group(1)): p
            for p in sorted(Path(journals).glob("ext-journal-*.csv"))
            if (m := re.search(r"(\d{4})", p.name))
        }
        selected = [y for y in sorted(files) if (not years or y in years) and y not in (exclude or [])]
        self.stdout.write(f"years: {selected} (excluded: {exclude})")
        source, _ = DataSource.objects.get_or_create(
            code="smvu-archive",
            defaults={"name": "Архив журналов СМВУ", "kind": DataSource.Kind.FILE, "adapter": "smvu_csv"},
        )

        parquets = []
        for year in selected:
            parquet = out_dir / f"journal_{year}.parquet"
            parquets.append(parquet)
            if reuse_parquet and parquet.exists():
                self.stdout.write(f"{year}: reuse {parquet.name}")
                continue
            job = ImportJob.objects.create(
                source=source,
                file_path=str(files[year]),
                params={"year": year},
                status=ImportJob.Status.RUNNING,
                started_at=timezone.now(),
            )
            started = time.monotonic()
            try:
                report = archive.normalize_journal(files[year], parquet, year=year)
                if not no_db:
                    report["daily_rows"] = archive.load_daily(archive.daily_frame(pl.scan_parquet(parquet)))
                job.quality = report
                job.rows_total, job.rows_ok = report["rows_total"], report["rows_loaded"]
                job.rows_skipped = report["rows_total"] - report["rows_loaded"]
                job.status = ImportJob.Status.DONE
            except Exception as exc:
                job.status, job.error = ImportJob.Status.FAILED, repr(exc)
                raise
            finally:
                job.finished_at = timezone.now()
                job.save()
            self.stdout.write(
                f"{year}: {report['rows_loaded']:,} of {report['rows_total']:,} rows "
                f"in {time.monotonic() - started:.0f}s → {parquet.name}"
            )
            self.stdout.write(json.dumps(report["summary"], ensure_ascii=False))

        if no_db or not parquets:
            return
        since = archive.window_start(parquets, raw_days)
        inserted = archive.load_readings(parquets, since)
        archive.refresh_hourly()
        self.stdout.write(
            self.style.SUCCESS(f"operational window since {since:%Y-%m-%d}: {inserted:,} readings")
        )
