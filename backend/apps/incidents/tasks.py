from celery import shared_task

from .services import escalate_overdue


@shared_task
def escalate_overdue_incidents() -> int:
    """Раз в минуту (celery beat): поднять по вертикали инциденты без реакции и пересчитать срочность."""
    from .analysis import refresh_open_priorities

    escalated = escalate_overdue()
    refresh_open_priorities()
    return escalated
