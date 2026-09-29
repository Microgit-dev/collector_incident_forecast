"""
Запуск обучения как задания с прогрессом: из интерфейса (Celery), по расписанию и из консоли —
одна логика. Здесь же решение «чемпион или претендент» и контроль деградации.
"""

from __future__ import annotations

import contextlib
import logging
import time
from datetime import timedelta

from django.utils import timezone

from .models import ForecastTask, LearningSettings, MLModel, Prediction, TrainingRun
from .services import activate, active_model

logger = logging.getLogger(__name__)


def execute(run: TrainingRun, echo=None) -> MLModel:
    from . import channel_model, feedback, specs
    from .domain.feedback import empty_labels

    spec = specs.get(run.task)
    settings = LearningSettings.load()
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
        horizon = int(run.params.get("horizon_hours", channel_model.HORIZON_HOURS))
        use_feedback = spec.uses_feedback and bool(run.params.get("use_feedback", settings.use_feedback))
        labels = feedback.accepted_labels(run.task) if use_feedback else empty_labels()
        current = active_model(run.task)
        same_horizon = current if current and current.horizon_hours == horizon else None
        result = channel_model.train(
            spec,
            progress,
            neg_rate=run.params.get("neg_rate"),
            horizon_hours=horizon,
            labels=labels,
            champion_artifact=same_horizon.artifact_path if same_horizon else None,
        )
        result.metrics["feedback"]["enabled"] = use_feedback
        model = MLModel.objects.create(
            task=run.task,
            version=result.version,
            algorithm="lightgbm",
            horizon_hours=horizon,
            status=MLModel.Status.READY,
            artifact_path=str(result.artifact),
            features=result.columns,
            params=result.params
            | {"use_feedback": use_feedback, "trigger": run.params.get("trigger", "manual")},
            metrics=result.metrics,
            train_period=result.train_period,
            notes=(
                f"Событие: {spec.event_title} в ближайшие {horizon} ч"
                + (f", уточнённые разметкой диспетчеров ({labels.height} меток)" if labels.height else "")
                + ". Выборка — каналы в норме на конец суток. Валидация по времени: обучение до 2025, "
                "подбор порогов на 2025, тест на 2026."
            ),
        )
        if use_feedback and result.per_label:
            feedback.record_usage(model, result.per_label)
        decision, reason = challenger_verdict(
            model, current, settings, forced=run.params.get("activate", False)
        )
        if decision:
            activate(model)
        model.metrics["comparison"]["verdict"] = reason
        model.save(update_fields=["metrics", "updated_at"])
        run.status, run.result_model = TrainingRun.Status.DONE, model
        run.progress, run.stage = 100, f"Готово: {reason}"
        run.log = f"test: {model.metrics['test']}"
        return model
    except channel_model.NotEnoughData as exc:
        logger.warning("training skipped: %s", exc)
        run.status, run.stage, run.log = TrainingRun.Status.FAILED, "Недостаточно данных", str(exc)
        raise
    except Exception as exc:
        logger.exception("training failed")
        run.status, run.stage, run.log = TrainingRun.Status.FAILED, "Ошибка", repr(exc)
        raise
    finally:
        run.finished_at = timezone.now()
        run.save()


def challenger_verdict(
    model: MLModel, current: MLModel | None, settings, forced: bool = False
) -> tuple[bool, str]:
    """
    Чемпион или претендент. Сравнение — на одной и той же валидации (с текущей разметкой):
    PR-AUC новой версии против PR-AUC действующей, пересчитанной на тех же строках.
    """
    if forced:
        return True, "активирована вручную"
    if current is None:
        return True, "первая модель — активирована"
    if current.horizon_hours != model.horizon_hours:
        return False, "другой горизонт — активируйте вручную, если нужен именно он"
    comparison = model.metrics.get("comparison", {})
    new, old = comparison.get("valid_pr_auc"), comparison.get("champion_valid_pr_auc")
    if old is None:
        old = current.metrics.get("valid", {}).get("pr_auc", 0)
    if new < old:
        return False, f"не принята: PR-AUC {new:.4f} хуже действующей {old:.4f}"
    if not settings.auto_activate:
        return False, f"лучше действующей ({new:.4f} против {old:.4f}), ждёт активации аналитиком"
    return True, f"активирована: PR-AUC {new:.4f} против {old:.4f}"


def check_degradation(now=None) -> dict:
    """
    Реализованная точность оперативного журнала за окно против ожидаемой (уровень «высокий»
    на валидации). Сильное падение — модель устарела или поток данных изменился.
    """
    settings = LearningSettings.load()
    model = active_model()
    now = now or timezone.now()
    result = {"checked_at": now.isoformat(), "status": "no_model"}
    if model is None:
        settings.last_check = result
        settings.save(update_fields=["last_check"])
        return result
    since = now - timedelta(days=settings.degradation_window_days)
    resolved = Prediction.objects.filter(
        model__task=model.task,
        is_backtest=False,
        issued_at__gte=since,
        outcome__in=["confirmed", "not_confirmed"],
    )
    total = resolved.count()
    confirmed = resolved.filter(outcome="confirmed").count()
    expected = model.metrics.get("valid", {}).get("precision")
    result |= {
        "model": model.version,
        "resolved": total,
        "confirmed": confirmed,
        "realized_precision": round(confirmed / total, 3) if total else None,
        "expected_precision": expected,
        "window_days": settings.degradation_window_days,
    }
    if total < settings.degradation_min_resolved or not expected:
        result["status"] = "not_enough_data"
    elif confirmed / total < settings.degradation_ratio * expected:
        result["status"] = "degraded"
        _alert_analysts(result)
        if settings.retrain_on_degradation:
            run = TrainingRun.objects.create(
                task=model.task, params={"horizon_hours": model.horizon_hours, "trigger": "degradation"}
            )
            from .tasks import train_model

            train_model.delay(run.pk)
            result["retrain_run"] = run.pk
    else:
        result["status"] = "ok"
    settings.last_check = result
    settings.save(update_fields=["last_check"])
    return result


def _alert_analysts(result: dict) -> None:
    from django.contrib.auth import get_user_model
    from django.db.models import Q

    from apps.notifications.services import notify

    users = (
        get_user_model()
        .objects.filter(is_active=True)
        .filter(
            Q(groups__permissions__codename="review_feedback")
            | Q(user_permissions__codename="review_feedback")
        )
        .distinct()
    )
    notify(
        list(users),
        title="Деградация модели прогноза",
        body=(
            f"Точность журнала за {result['window_days']} сут — {result['realized_precision']:.0%} "
            f"при ожидаемой {result['expected_precision']:.0%}. Проверьте разметку и переобучите модель."
        ),
        level="high",
        link="/learning",
        payload={"kind": "degradation"},
    )


def scheduled_retrain() -> int | None:
    """Плановое переобучение (раз в неделю, если включено в настройках)."""
    settings = LearningSettings.load()
    if not settings.retrain_weekly:
        return None
    if TrainingRun.objects.filter(
        status__in=[TrainingRun.Status.PENDING, TrainingRun.Status.RUNNING]
    ).exists():
        return None
    run = TrainingRun.objects.create(
        task=ForecastTask.SENSOR_FAILURE,
        params={"horizon_hours": settings.horizon_hours, "trigger": "schedule"},
    )
    from .channel_model import NotEnoughData

    # истории мало: причина записана в запуск, активная модель остаётся прежней
    with contextlib.suppress(NotEnoughData):
        execute(run)
    return run.pk
