"""
Реактивные правила: смена состояния канала → алерт. Дополняют прогнозные модели:
модель предупреждает заранее, правило фиксирует факт.

Срабатывают только на свежие события (RECENCY): пакетная загрузка истории
не должна заваливать диспетчера инцидентами за прошлые годы.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from django.dispatch import receiver
from django.utils import timezone

from apps.assets.models import Channel, IncidentDomain
from apps.forecasting.models import RiskLevel
from apps.normalization.domain.engine import State
from apps.telemetry.signals import channel_states_changed

from .domain.correlation import PHYSICAL, TECHNICAL, contour
from .models import Alert, IncidentType
from .services import SignalIn, register_signals

logger = logging.getLogger(__name__)

RECENCY = timedelta(minutes=15)

_DOMAIN_TO_TYPE = {
    IncidentDomain.FIRE: IncidentType.FIRE,
    IncidentDomain.GAS: IncidentType.GAS,
    IncidentDomain.FLOOD: IncidentType.FLOOD,
    IncidentDomain.INTRUSION: IncidentType.INTRUSION,
    IncidentDomain.POWER: IncidentType.POWER,
    IncidentDomain.PROCESS: IncidentType.EQUIPMENT,
    IncidentDomain.CLIMATE: IncidentType.FIRE,
}
_ALARM_SEVERITY = {
    IncidentType.FIRE: RiskLevel.CRITICAL,
    IncidentType.GAS: RiskLevel.CRITICAL,
    IncidentType.FLOOD: RiskLevel.HIGH,
    IncidentType.INTRUSION: RiskLevel.HIGH,
    IncidentType.POWER: RiskLevel.MEDIUM,
    IncidentType.EQUIPMENT: RiskLevel.MEDIUM,
}


@receiver(channel_states_changed)
def on_states_changed(sender, changes, **kwargs):
    """Пачка смен состояния → сигналы, сгруппированные по объекту и контуру → эпизоды."""
    threshold = timezone.now() - RECENCY
    fresh = [c for c in changes if c.ts >= threshold and c.current != c.previous]
    if not fresh:
        return
    channels = Channel.objects.select_related("sensor_type", "node").in_bulk({c.channel_id for c in fresh})
    groups: dict[tuple, list[SignalIn]] = defaultdict(list)
    nodes = {}
    for change in fresh:
        channel = channels.get(change.channel_id)
        if channel is None:
            continue
        domain = channel.sensor_type.domain if channel.sensor_type else IncidentDomain.PROCESS
        if change.current == State.ALARM:
            incident_type = _DOMAIN_TO_TYPE.get(domain, IncidentType.EQUIPMENT)
            severity = _ALARM_SEVERITY[incident_type]
            title = f"{IncidentType(incident_type).label}: {channel.name}"
        elif change.current == State.FAULT:
            incident_type, severity = IncidentType.SENSOR_FAILURE, RiskLevel.MEDIUM
            title = f"Неисправность датчика: {channel.name}"
        elif change.current == State.POWER_LOSS:
            incident_type, severity = IncidentType.POWER, RiskLevel.MEDIUM
            title = f"Потеря питания: {channel.name}"
        elif change.current == State.UNKNOWN:
            incident_type, severity = IncidentType.COMMUNICATION, RiskLevel.LOW
            title = f"Состояние не определено: {channel.name}"
        else:
            continue
        # Физические угрозы группируются по типу, технические — одним эпизодом объекта
        key = (channel.node_id, incident_type if contour(incident_type) == PHYSICAL else TECHNICAL)
        nodes[channel.node_id] = channel.node
        groups[key].append(
            SignalIn(
                title=title,
                severity=severity,
                ts=change.ts,
                channel=channel,
                state=change.current,
                details={"facet": change.facet, "previous": change.previous, "numeric": change.numeric},
            )
        )
    for (node_id, kind), signals in groups.items():
        incident_type = kind if kind != TECHNICAL else IncidentType.SENSOR_FAILURE
        register_signals(type=incident_type, node=nodes[node_id], source=Alert.Source.RULE, signals=signals)
