import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def sync_weather() -> int:
    """Последние сутки и прогноз осадков — признаки оперативного прогноза подтоплений."""
    from .weather import sync_recent

    try:
        return sync_recent()
    except Exception:  # внешний API недоступен — прогноз работает без свежей погоды
        logger.warning("Open-Meteo недоступен", exc_info=True)
        return 0


@shared_task(ignore_result=True)
def sync_registry() -> dict:
    """Раз в сутки: реестр оборудования из учётной системы заказчика (только при REGISTRY_MODE=api)."""
    from .clients import conf
    from .registry import sync

    if conf("REGISTRY_MODE") != "api":
        return {}
    return sync("registry")
