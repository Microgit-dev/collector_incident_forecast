"""
Срочный пересчёт прогноза: смена состояния канала (неисправность, питание, «не определено»)
меняет признаки объекта, и ждать планового цикла (15 минут) не нужно. Пересчёт по объекту
откладывается на минуту и не дублируется: пачка событий по объекту даёт один пересчёт.
"""

from datetime import timedelta

from django.core.cache import cache
from django.dispatch import receiver
from django.utils import timezone

from apps.normalization.domain.engine import State
from apps.telemetry.signals import channel_states_changed

TRIGGERS = {State.FAULT, State.POWER_LOSS, State.UNKNOWN, State.WARNING}
DEBOUNCE_SECONDS = 60
RECENCY = timedelta(minutes=15)


@receiver(channel_states_changed)
def on_states_changed(sender, changes, **kwargs):
    from apps.assets.models import Channel

    from .tasks import forecast_nodes

    threshold = timezone.now() - RECENCY
    ids = {
        c.channel_id
        for c in changes
        if c.current in TRIGGERS and c.current != c.previous and c.ts >= threshold
    }
    if not ids:
        return
    nodes = set(Channel.objects.filter(pk__in=ids).values_list("node_id", flat=True))
    fresh = [n for n in nodes if cache.add(f"forecast:urgent:{n}", 1, DEBOUNCE_SECONDS)]
    if fresh:
        forecast_nodes.apply_async(args=[sorted(fresh)], countdown=DEBOUNCE_SECONDS)
