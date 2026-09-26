from celery import shared_task


@shared_task
def exercise_tick() -> dict:
    """Раз в 15 с (celery beat): учения по таймеру, напоминания, завершение по длительности."""
    from .exercises import tick

    return tick()


@shared_task
def exercise_complication(exercise_id: int) -> bool:
    """Осложнение сценария через заданное время после старта (если учения ещё идут)."""
    from .exercises import complicate

    return complicate(exercise_id)
