from celery import shared_task


@shared_task
def sync_identity() -> dict:
    """Учебный контур: учётки, роли и команды из основной системы (раз в 5 минут)."""
    from .identity import sync_all

    return sync_all()
