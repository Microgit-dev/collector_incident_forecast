from celery import shared_task


@shared_task
def generate_recommendations() -> dict:
    """Раз в сутки: рекомендации по ТО из прогнозов, качества данных и реестра оборудования."""
    from .recommendations import generate

    return generate()
