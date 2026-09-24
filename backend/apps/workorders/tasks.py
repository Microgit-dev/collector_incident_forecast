from celery import shared_task


@shared_task
def generate_recommendations() -> dict:
    """Раз в сутки: рекомендации по ТО из прогнозов, качества данных и реестра оборудования."""
    from .recommendations import generate

    return generate()


@shared_task(ignore_result=True)
def sync_helpdesk() -> dict:
    """Раз в минуту: статусы переданных заявок из системы учёта заявок (только чтение)."""
    from .services import sync_external

    return sync_external()
