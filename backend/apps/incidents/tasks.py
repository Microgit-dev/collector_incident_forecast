from celery import shared_task

from .services import escalate_overdue


@shared_task
def escalate_overdue_incidents() -> int:
    """Раз в минуту (celery beat): поднять по вертикали инциденты без реакции."""
    return escalate_overdue()
