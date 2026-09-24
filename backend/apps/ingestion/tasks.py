import logging

from celery import shared_task
from django.utils import timezone

from .adapters import REGISTRY
from .models import ImportJob
from .pipeline import Pipeline

logger = logging.getLogger(__name__)

BATCH = 5000


@shared_task(bind=True)
def run_import_job(self, job_id: int) -> dict:
    """Пакетный импорт исторических данных тем же конвейером, что и поток."""
    job = ImportJob.objects.select_related("source").get(pk=job_id)
    job.status, job.started_at = ImportJob.Status.RUNNING, timezone.now()
    job.save(update_fields=["status", "started_at"])
    pipeline = Pipeline()
    adapter = REGISTRY[job.source.adapter]
    path = job.file.path if job.file else job.file_path
    try:
        batch = []
        for event in adapter.iter_events(path=path, **job.source.config, **job.params):
            batch.append(event)
            if len(batch) >= BATCH:
                _flush(job, pipeline, batch)
                batch = []
        _flush(job, pipeline, batch)
        job.status = ImportJob.Status.DONE
    except Exception as exc:
        logger.exception("import job %s failed", job_id)
        job.status, job.error = ImportJob.Status.FAILED, str(exc)
    job.finished_at = timezone.now()
    job.save()
    return {"job": job.pk, "status": job.status, "rows_ok": job.rows_ok}


def _flush(job: ImportJob, pipeline: Pipeline, batch: list) -> None:
    if not batch:
        return
    result = pipeline.process(batch)
    job.rows_total += result.received
    job.rows_ok += result.stored
    job.rows_skipped += result.skipped_unknown_channel
    quality = job.quality or {"by_quality": {}, "by_state": {}}
    for key, counter in (("by_quality", result.by_quality), ("by_state", result.by_state)):
        for name, count in counter.items():
            quality[key][name] = quality[key].get(name, 0) + count
    job.quality = quality
    job.save(update_fields=["rows_total", "rows_ok", "rows_skipped", "quality"])
