from __future__ import annotations

from collections import defaultdict
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
    """
    Текущее состояние канала — по последнему событию, но смены состояния считаются по всей пачке
    в порядке времени: кратковременная тревога, снятая в той же пачке, тоже становится сигналом.
    """
    per_key: dict[tuple[int, str], list[NormalizedReading]] = defaultdict(list)
    for item in items:
        per_key[(item.channel_id, item.value.facet)].append(item)

    channel_ids = {cid for cid, _ in per_key}
    existing = {
        (s.channel_id, s.facet): s
        for s in ChannelState.objects.select_for_update().filter(channel_id__in=channel_ids)
    }
    to_create, to_update, changes = [], [], []
    for key, seq in per_key.items():
        seq.sort(key=lambda i: i.ts)
        current = existing.get(key)
        if current is not None:
            seq = [i for i in seq if i.ts >= current.last_seen_at]  # опоздавшие не откатывают состояние
            if not seq:
                continue
        previous = State(current.state) if current is not None else None
        changed_at = current.changed_at if current is not None else seq[0].ts
        for item in seq:
            if item.value.state != previous:
                changes.append(
                    StateChange(key[0], key[1], previous, item.value.state, item.ts, item.value.numeric)
                )
                changed_at = item.ts
            previous = item.value.state
        last = seq[-1]
        if current is None:
            to_create.append(
                ChannelState(
                    channel_id=key[0],
                    facet=key[1],
                    state=last.value.state,
                    numeric=last.value.numeric,
                    raw_value=last.raw_value[:255],
                    changed_at=changed_at,
                    last_seen_at=last.ts,
                )
            )
            continue
        current.state = last.value.state
        current.numeric = last.value.numeric
        current.raw_value = last.raw_value[:255]
        current.changed_at = changed_at
        current.last_seen_at = last.ts
        to_update.append(current)

    ChannelState.objects.bulk_create(to_create, ignore_conflicts=True)
    ChannelState.objects.bulk_update(
        to_update, ["state", "numeric", "raw_value", "changed_at", "last_seen_at"]
    )
    return changes
