import pytest
from django.utils import timezone

from apps.assets.models import Channel, SensorType
from apps.incidents.models import Incident
from apps.normalization.domain.defaults import GLOBAL_RULES
from apps.normalization.domain.engine import Profile, ValueKind, normalize
from apps.telemetry.services import NormalizedReading, store_readings

DISCRETE = Profile(code="discrete", value_kind=ValueKind.STATE)


@pytest.fixture
def motion_channel(tree):
    sensor = SensorType.objects.create(name="Датчик движения", domain="intrusion")
    return Channel.objects.create(external_id=1, node=tree["house"], sensor_type=sensor, name="ОД ПК1")


def _push(channel, event_id, raw, raw_alarm=None):
    return store_readings(
        [
            NormalizedReading(
                event_id=event_id,
                channel_id=channel.pk,
                ts=timezone.now(),
                raw_value=raw,
                raw_alarm=raw_alarm,
                value=normalize(raw, DISCRETE, GLOBAL_RULES, raw_alarm),
            )
        ]
    )


def test_transition_to_fault_opens_incident_once(motion_channel):
    _push(motion_channel, 1, "Норма")
    _push(motion_channel, 2, "Неисправен")
    _push(motion_channel, 3, "Неисправен")  # повтор того же состояния — не новое событие
    incident = Incident.objects.get()
    assert (incident.type, incident.alerts.count()) == ("sensor_failure", 1)


def test_unguarded_motion_is_not_an_incident(motion_channel):
    _push(motion_channel, 1, "Движения нет", raw_alarm=False)
    _push(motion_channel, 2, "Обнаружено движение", raw_alarm=False)
    assert not Incident.objects.exists()
    _push(motion_channel, 3, "Движения нет", raw_alarm=False)
    _push(motion_channel, 4, "Обнаружено движение", raw_alarm=True)
    assert Incident.objects.get().type == "intrusion"
