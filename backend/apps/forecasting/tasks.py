import logging

from celery import shared_task

from .models import TrainingRun

logger = logging.getLogger(__name__)


@shared_task
def run_forecast_cycle() -> dict:
    """Периодический прогноз (celery beat, раз в 15 минут): качество данных, молчание, риск отказа."""
    from .services import run_cycle

    return run_cycle()


@shared_task
def forecast_nodes(node_ids: list[int]) -> dict:
    """Срочный пересчёт по объектам после смены состояния их каналов."""
    from .services import run_cycle

    return run_cycle(node_ids=node_ids)


@shared_task
def backtest_recent(days: int = 30) -> dict:
    """Бэктест активной модели за последние N суток до «времени данных» (шаг — сутки)."""
    from datetime import timedelta

    from .data import data_clock
    from .services import backtest

    end = data_clock()
    if end is None:
        return {"status": "no data"}
    return backtest(end - timedelta(days=days), end - timedelta(days=1))


@shared_task(acks_late=True)
def train_model(run_id: int) -> dict:
    from .training import execute

    run = TrainingRun.objects.get(pk=run_id)
    model = execute(run)
    return {"run": run_id, "model": model.pk, "status": model.status}
