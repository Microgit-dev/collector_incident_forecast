"""
Импорт истории журналов СМВУ пакетами: одно задание на год + задание «оперативное окно».

Заказчик получает стенд без данных и сам кладёт журналы в каталог данных. Импорт запускается
из интерфейса (фоновая задача Celery) или консоли — логика одна. Прогресс каждого задания
пишется в ImportJob, интерфейс показывает его по пакету.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import polars as pl
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.assets.models import Channel
from apps.topology.models import Node

from . import archive
from .models import DataSource, ImportJob

logger = logging.getLogger(__name__)

# 2021: всплеск тревог из-за перехода на новую систему мониторинга — заказчик рекомендует исключить
EXCLUDED_YEARS = frozenset({2021})
ACTIVE = (ImportJob.Status.PENDING, ImportJob.Status.RUNNING)
# Задание без обновления прогресса дольше этого срока считается зависшим (упал воркер/Docker)
STALE_AFTER = timedelta(minutes=30)
_YEAR = re.compile(r"(\d{4})")


class ImportBusy(Exception):
    """Уже идёт другой импорт истории: параллельный запуск перегрузил бы память и БД."""


def journals_dir() -> Path:
    return settings.DATA_DIR / "dataset" / "journals"


def archive_dir() -> Path:
    return settings.ARTIFACTS_DIR / "archive"


def available_journals() -> list[dict]:
    """Файлы журналов в каталоге данных и статус их последнего импорта."""
    last = {}
    for job in ImportJob.objects.filter(kind=ImportJob.Kind.HISTORY).order_by("created_at"):
        if year := job.params.get("year"):
            last[year] = job
    result = []
    for path in sorted(journals_dir().glob("*.csv")):
        match = _YEAR.search(path.name)
        if not match:
            continue
        year = int(match.group(1))
        job = last.get(year)
        result.append(
            {
                "year": year,
                "file": path.name,
                "size_mb": round(path.stat().st_size / 2**20),
                "excluded": year in EXCLUDED_YEARS,
                "exclude_reason": "переход на новую систему мониторинга" if year in EXCLUDED_YEARS else "",
                "last_status": job.status if job else None,
                "last_rows": job.rows_ok if job else None,
                "last_finished_at": job.finished_at.isoformat() if job and job.finished_at else None,
            }
        )
    return result


def reference_status() -> dict:
    base = settings.DATA_DIR / "dataset"
    return {
        "objects_file": (base / "справочник_объектов_диспетчер.csv").exists(),
        "channels_file": (base / "справочник_каналов_датчиков.csv").exists(),
        "objects": Node.objects.exclude(external_id=None).count(),
        "channels": Channel.objects.filter(in_catalog=True).count(),
    }


def _source() -> DataSource:
    source, _ = DataSource.objects.get_or_create(
        code="smvu-archive",
        defaults={"name": "Архив журналов СМВУ", "kind": DataSource.Kind.FILE, "adapter": "smvu_csv"},
    )
    return source


@transaction.atomic
def plan(years: list[int], raw_days: int = 30, user=None) -> uuid.UUID:
    """Создаёт задания пакета в статусе «в очереди» — интерфейс сразу видит весь план."""
    ImportJob.objects.filter(
        kind__in=["history", "window"], status__in=ACTIVE, updated_at__lt=timezone.now() - STALE_AFTER
    ).update(status=ImportJob.Status.FAILED, stage="Прервано", error="Нет прогресса более 30 минут")
    if (
        ImportJob.objects.select_for_update()
        .filter(kind__in=["history", "window"], status__in=ACTIVE)
        .exists()
    ):
        raise ImportBusy("Импорт истории уже выполняется — дождитесь его завершения")
    files = {j["year"]: j["file"] for j in available_journals()}
    missing = [y for y in years if y not in files]
    if missing:
        raise FileNotFoundError(f"Нет файлов журналов за {', '.join(map(str, missing))}")
    if not years:
        raise ValueError("Не выбран ни один год")
    batch = uuid.uuid4()
    source = _source()
    for year in sorted(years):
        ImportJob.objects.create(
            kind=ImportJob.Kind.HISTORY,
            batch=batch,
            source=source,
            created_by=user,
            file_path=str(journals_dir() / files[year]),
            params={"year": year},
            stage="В очереди",
        )
    ImportJob.objects.create(
        kind=ImportJob.Kind.WINDOW,
        batch=batch,
        source=source,
        created_by=user,
        params={"raw_days": raw_days, "years": sorted(years)},
        stage="В очереди",
    )
    return batch


class Reporter:
    """Пишет прогресс задания в БД не чаще раза в секунду и дублирует его в консоль."""

    def __init__(self, job: ImportJob, echo: Callable[[str], None] | None):
        self.job, self.echo, self._last = job, echo, 0.0

    def __call__(self, fraction: float, stage: str) -> None:
        now = time.monotonic()
        if now - self._last < 1 and fraction < 1:
            return
        self._last = now
        self.job.progress, self.job.stage = round(min(fraction, 1) * 100, 1), stage[:128]
        ImportJob.objects.filter(pk=self.job.pk).update(
            progress=self.job.progress, stage=self.job.stage, updated_at=timezone.now()
        )
        if self.echo:
            label = self.job.params.get("year") or self.job.get_kind_display()
            self.echo(f"[{label}] {self.job.progress:5.1f}%  {stage}")


def start_job(job: ImportJob) -> None:
    job.status, job.started_at, job.error = ImportJob.Status.RUNNING, timezone.now(), ""
    job.save(update_fields=["status", "started_at", "error"])


def finish_job(job: ImportJob, error: Exception | None = None) -> None:
    job.finished_at = timezone.now()
    if error is None:
        job.status, job.progress, job.stage = ImportJob.Status.DONE, 100, "Готово"
    else:
        job.status, job.error, job.stage = ImportJob.Status.FAILED, repr(error), "Ошибка"
    job.save()


def run_year(job: ImportJob, echo=None) -> None:
    year = job.params["year"]
    parquet = archive_dir() / f"journal_{year}.parquet"
    report_progress = Reporter(job, echo)
    start_job(job)
    try:
        # Импорт года с нуля: прежние отчёты по этому году заменяются новым
        ImportJob.objects.filter(kind=ImportJob.Kind.HISTORY, params__year=year).exclude(
            batch=job.batch
        ).delete()
        report = archive.normalize_journal(
            Path(job.file_path),
            parquet,
            year=year,
            progress=lambda f, s: report_progress(f * 0.9, s),
        )
        daily = archive.daily_frame(
            pl.scan_parquet(parquet), progress=lambda f, s: report_progress(0.9 + f * 0.08, s)
        )
        report_progress(0.98, "Запись суточной витрины")
        report["daily_rows"] = archive.load_daily(daily)
        job.quality = report
        job.rows_total, job.rows_ok = report["rows_total"], report["rows_loaded"]
        job.rows_skipped = report["rows_total"] - report["rows_loaded"]
        finish_job(job)
    except Exception as exc:
        logger.exception("history import of %s failed", year)
        finish_job(job, exc)
        raise


def run_window(job: ImportJob, echo=None) -> None:
    report_progress = Reporter(job, echo)
    start_job(job)
    try:
        parquets = sorted(archive_dir().glob("journal_*.parquet"))
        if not parquets:
            raise FileNotFoundError("Архив пуст — нечего загружать в оперативный контур")
        raw_days = job.params.get("raw_days", 30)
        since = archive.window_start(parquets, raw_days)
        report_progress(0.05, f"Окно с {since:%d.%m.%Y}")
        inserted = archive.load_readings(parquets, since, progress=report_progress)
        report_progress(0.96, "Почасовая витрина")
        archive.refresh_hourly()
        job.rows_ok = job.rows_total = inserted
        job.params = {**job.params, "since": since.isoformat()}
        finish_job(job)
    except Exception as exc:
        logger.exception("operational window load failed")
        finish_job(job, exc)
        raise


def run_batch(batch: uuid.UUID, echo=None) -> None:
    """Выполняет задания пакета по очереди. Ошибка года не останавливает остальные годы."""
    jobs = list(ImportJob.objects.filter(batch=batch).order_by("kind", "params__year"))
    failed = False
    for job in (j for j in jobs if j.kind == ImportJob.Kind.HISTORY):
        try:
            run_year(job, echo)
        except Exception:
            failed = True
    for job in (j for j in jobs if j.kind == ImportJob.Kind.WINDOW):
        run_window(job, echo)
    # даты ввода эмулированного оборудования берутся из первого появления канала в журналах
    from apps.assets.registry import emulate_registry

    registry = emulate_registry()
    if echo:
        echo(f"equipment registry: {registry}")
    if failed:
        raise RuntimeError("Часть лет не загружена — подробности в заданиях импорта")
