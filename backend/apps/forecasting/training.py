"""Запуск обучения как задания с прогрессом: из интерфейса (Celery) и из консоли — одна логика."""

from __future__ import annotations

import logging
import time

from django.utils import timezone

from .models import ForecastTask, MLModel, TrainingRun
from .services import activate, active_model

logger = logging.getLogger(__name__)


def execute(run: TrainingRun, echo=None) -> MLModel:
    from . import sensor_failure

    if run.task != ForecastTask.SENSOR_FAILURE:
        raise ValueError(f"Для задачи {run.get_task_display()} используется правило, обучение не требуется")
    last = [0.0]

    def progress(fraction: float, stage: str) -> None:
        now = time.monotonic()
        if now - last[0] < 1 and fraction < 1:
            return
        last[0] = now
        TrainingRun.objects.filter(pk=run.pk).update(progress=round(fraction * 100, 1), stage=stage[:128])
        if echo:
            echo(f"{fraction:6.1%}  {stage}")

    run.status, run.stage, run.progress = TrainingRun.Status.RUNNING, "Старт", 0
    run.save(update_fields=["status", "stage", "progress", "updated_at"])
    try:
        horizon = int(run.params.get("horizon_hours", sensor_failure.HORIZON_HOURS))
        result = sensor_failure.train(
            progress, neg_rate=run.params.get("neg_rate", sensor_failure.NEG_RATE), horizon_hours=horizon
        )
        model = MLModel.objects.create(
            task=run.task,
            version=result.version,
            algorithm="lightgbm",
            horizon_hours=horizon,
            status=MLModel.Status.READY,
            artifact_path=str(result.artifact),
            features=sensor_failure.matrix_columns(),
            params=result.params,
            metrics=result.metrics,
            train_period=result.train_period,
            notes=(
                f"Слабые метки: неисправность канала в ближайшие {horizon} ч (fault, служебные коды, дата 1970). "
                "Выборка — каналы, исправные на конец суток. Валидация по времени: обучение до 2025, "
                "подбор порогов на 2025, тест на 2026."
            ),
        )
        current = active_model(run.task)
        # Автоматически заменяем активную версию только моделью того же горизонта с не худшей валидацией:
        # PR-AUC разных горизонтов несравнимы (у 7 суток выше доля положительных)
        better = current is None or (
            current.horizon_hours == model.horizon_hours
            and model.metrics["valid"]["pr_auc"] >= current.metrics.get("valid", {}).get("pr_auc", 0)
        )
        if better or run.params.get("activate"):
            activate(model)
        run.status, run.result_model = TrainingRun.Status.DONE, model
        kept = "" if model.status == MLModel.Status.ACTIVE else " (активной осталась прежняя версия)"
        run.progress, run.stage = 100, f"Готово{kept}"
        run.log = f"test: {model.metrics['test']}"
        return model
    except Exception as exc:
        logger.exception("training failed")
        run.status, run.stage, run.log = TrainingRun.Status.FAILED, "Ошибка", repr(exc)
        raise
    finally:
        run.finished_at = timezone.now()
        run.save()
