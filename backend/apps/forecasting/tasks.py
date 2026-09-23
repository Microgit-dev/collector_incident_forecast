import logging

from celery import shared_task
from django.utils import timezone

from .models import TrainingRun

logger = logging.getLogger(__name__)


@shared_task
def run_forecast_cycle() -> dict:
    """
    Периодический прогноз по всем активным моделям (celery beat).
    Реализация — E3: собрать признаки на as_of, вызвать Forecaster, записать Prediction,
    для уровня ≥ RiskPolicy.alert_from_level создать алерт.
    """
    logger.info("forecast cycle: no active forecasters yet")
    return {"predictions": 0}


@shared_task
def train_model(run_id: int) -> dict:
    """Обучение/дообучение модели по задаче. Реализация — E3 (признаки из Parquet/Timescale, LightGBM)."""
    run = TrainingRun.objects.get(pk=run_id)
    run.status = TrainingRun.Status.FAILED
    run.log = "Пайплайн обучения ещё не подключён (E3)"
    run.finished_at = timezone.now()
    run.save()
    return {"run": run_id, "status": run.status}
