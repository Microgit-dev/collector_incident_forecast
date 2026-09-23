from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

from apps.normalization.domain.engine import Normalized, State

from .models import ChannelState, Reading
from .signals import channel_states_changed


@dataclass(frozen=True, slots=True)
class NormalizedReading:
    event_id: int
    channel_id: int
    ts: datetime
    raw_value: str
    raw_alarm: bool | None
    value: Normalized


@dataclass(frozen=True, slots=True)
class StateChange:
    channel_id: int
    facet: str
    previous: State | None
    current: State
    ts: datetime
    numeric: float | None


@transaction.atomic
def store_readings(items: list[NormalizedReading]) -> list[StateChange]:
    """
    Пишет показания в hypertable и обновляет текущие состояния каналов.
    Возвращает смены состояний и рассылает сигнал — на него подписаны правила инцидентов.
    """
    if not items:
        return []
    Reading.objects.bulk_create(
        [
            Reading(
                ts=i.ts,
                event_id=i.event_id,
                channel_id=i.channel_id,
                raw_value=i.raw_value[:255],
                raw_alarm=i.raw_alarm,
                numeric=i.value.numeric,
                state=i.value.state,
                facet=i.value.facet,
                quality=i.value.quality,
            )
            for i in items
        ],
        batch_size=5000,
        ignore_conflicts=True,  # повторная доставка из Kafka идемпотентна
    )
    changes = _apply_latest_states(items)
    if changes:
        channel_states_changed.send(sender=StateChange, changes=changes)
    return changes


def _apply_latest_states(items: list[NormalizedReading]) -> list[StateChange]:
    latest: dict[tuple[int, str], NormalizedReading] = {}
    for item in items:
        key = (item.channel_id, item.value.facet)
        if key not in latest or item.ts >= latest[key].ts:
            latest[key] = item

    channel_ids = {cid for cid, _ in latest}
    existing = {
        (s.channel_id, s.facet): s
        for s in ChannelState.objects.select_for_update().filter(channel_id__in=channel_ids)
    }
    to_create, to_update, changes = [], [], []
    for key, item in latest.items():
        current = existing.get(key)
        new_state = item.value.state
        if current is None:
            to_create.append(
                ChannelState(
                    channel_id=key[0],
                    facet=key[1],
                    state=new_state,
                    numeric=item.value.numeric,
                    raw_value=item.raw_value[:255],
                    changed_at=item.ts,
                    last_seen_at=item.ts,
                )
            )
            changes.append(StateChange(key[0], key[1], None, new_state, item.ts, item.value.numeric))
            continue
        if item.ts < current.last_seen_at:
            continue  # опоздавшее событие не откатывает более свежее состояние
        if current.state != new_state:
            changes.append(
                StateChange(key[0], key[1], State(current.state), new_state, item.ts, item.value.numeric)
            )
            current.changed_at = item.ts
        current.state = new_state
        current.numeric = item.value.numeric
        current.raw_value = item.raw_value[:255]
        current.last_seen_at = item.ts
        to_update.append(current)

    ChannelState.objects.bulk_create(to_create, ignore_conflicts=True)
    ChannelState.objects.bulk_update(
        to_update, ["state", "numeric", "raw_value", "changed_at", "last_seen_at"]
    )
    return changes
