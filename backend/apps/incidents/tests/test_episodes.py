from datetime import UTC, datetime, timedelta

import pytest

from apps.assets.models import Channel, IncidentDomain, SensorType
from apps.forecasting.models import RiskLevel
from apps.incidents import services
from apps.incidents.domain.correlation import Context, Signal, hypotheses
from apps.incidents.domain.priority import PriorityInput, priority
from apps.incidents.models import Alert, Incident, IncidentType
from apps.incidents.services import SignalIn

NIGHT = datetime(2026, 6, 30, 23, 0, tzinfo=UTC)


@pytest.fixture
def channels(tree):
    smoke = SensorType.objects.create(name="Датчик дыма", domain=IncidentDomain.FIRE)
    return [
        Channel.objects.create(
            external_id=i, node=tree["house"], sensor_type=smoke, name=f"Дым ПК{i}", picket=i
        )
        for i in range(1, 25)
    ]


def _signal(channel, state, ts, severity=RiskLevel.MEDIUM, title=None):
    return SignalIn(
        title=title or f"{state}: {channel.name}", severity=severity, ts=ts, channel=channel, state=state
    )


def test_power_cascade_becomes_one_episode(tree, channels, make_user, django_capture_on_commit_callbacks):
    dispatcher = make_user("disp", "unit_dispatcher", tree["house"])
    now = datetime.now(UTC)
    signals = [
        _signal(ch, "power_loss" if i % 2 else "fault", now + timedelta(seconds=i))
        for i, ch in enumerate(channels[:20])
    ]
    with django_capture_on_commit_callbacks(execute=True):
        services.register_signals(
            type=IncidentType.SENSOR_FAILURE,
            node=tree["house"],
            source=Alert.Source.RULE,
            signals=signals[:10],
        )
        services.register_signals(
            type=IncidentType.SENSOR_FAILURE,
            node=tree["house"],
            source=Alert.Source.RULE,
            signals=signals[10:],
        )

    incident = Incident.objects.get()
    assert (incident.signals_count, incident.channels_count) == (20, 20)
    assert incident.type == IncidentType.POWER and incident.contour == "technical"
    assert incident.hypotheses[0]["code"] == "power"
    assert incident.actions[0]["code"] == "check_feeder"
    assert "каналов 20" in incident.title
    # одно уведомление на весь каскад: тип уточнён ещё до уведомления об открытии
    assert dispatcher.notifications.count() == 1


def test_physical_threats_do_not_merge(tree, channels):
    now = datetime.now(UTC)
    services.register_signals(
        type=IncidentType.FIRE,
        node=tree["house"],
        source=Alert.Source.RULE,
        signals=[_signal(channels[0], "alarm", now, RiskLevel.CRITICAL)],
    )
    services.register_signals(
        type=IncidentType.INTRUSION,
        node=tree["house"],
        source=Alert.Source.RULE,
        signals=[_signal(channels[1], "alarm", now, RiskLevel.HIGH)],
    )
    services.register_signals(
        type=IncidentType.SENSOR_FAILURE,
        node=tree["house"],
        source=Alert.Source.RULE,
        signals=[_signal(channels[2], "fault", now)],
    )
    assert Incident.objects.count() == 3
    fire = Incident.objects.get(type=IncidentType.FIRE)
    technical = Incident.objects.get(contour="technical")
    assert fire.priority > technical.priority


def test_window_slides_with_the_episode(tree, channels):
    start = datetime.now(UTC) - timedelta(hours=2)
    for i in range(5):  # сигнал каждые 25 минут — эпизод продолжается больше часа
        services.register_signals(
            type=IncidentType.SENSOR_FAILURE,
            node=tree["house"],
            source=Alert.Source.RULE,
            signals=[_signal(channels[i], "fault", start + timedelta(minutes=25 * i))],
        )
    assert Incident.objects.count() == 1
    services.register_signals(
        type=IncidentType.SENSOR_FAILURE,
        node=tree["house"],
        source=Alert.Source.RULE,
        signals=[_signal(channels[9], "fault", start + timedelta(minutes=100 + 45))],
    )
    assert Incident.objects.count() == 2


def test_checklist_step_is_recorded(tree, channels, make_user):
    user = make_user("disp", "unit_dispatcher", tree["house"])
    alert = services.raise_alert(
        type=IncidentType.FIRE,
        severity=RiskLevel.CRITICAL,
        node=tree["house"],
        channel=channels[0],
        title="Пожар",
        source=Alert.Source.RULE,
        details={"state": "alarm"},
    )
    incident = alert.incident
    code = incident.actions[0]["code"]
    incident = services.mark_action(incident, user, code)
    assert incident.actions[0]["done"] and incident.actions[0]["done_by"] == "disp"
    assert incident.events.filter(kind="action_done").exists()
    with pytest.raises(services.IncidentError):
        services.mark_action(incident, user, "nope")


def _sig(channel_id, state="alarm", seconds=0, **kw):
    return Signal(channel_id=channel_id, state=state, ts=NIGHT + timedelta(seconds=seconds), **kw)


def test_fire_confirmed_by_neighbours_beats_false_alarm():
    confirmed = hypotheses(
        "fire", [_sig(1), _sig(2, seconds=30), _sig(3, seconds=40)], Context(local_time=NIGHT)
    )
    assert confirmed[0].code == "fire"
    single_flaky = hypotheses("fire", [_sig(1, fault_history=6, health=40)], Context(local_time=NIGHT))
    assert single_flaky[0].code == "false"


def test_intrusion_during_works_points_to_authorized_access():
    day = datetime(2026, 6, 30, 11, 0, tzinfo=UTC)
    ranked = hypotheses(
        "intrusion",
        [Signal(channel_id=1, state="alarm", ts=day)],
        Context(local_time=day, works_in_progress=1),
    )
    assert ranked[0].code == "works"
    assert abs(sum(h.weight for h in ranked) - 1) < 1e-9


def test_single_sensor_with_history_is_sensor_hypothesis():
    ranked = hypotheses(
        "sensor_failure", [_sig(1, state="fault", fault_history=5, name="Дым ПК1")], Context(local_time=NIGHT)
    )
    assert ranked[0].code == "sensor"
    assert "5 неисправностей" in ranked[0].evidence[0]


def test_priority_grows_with_overdue_and_escalation():
    base = dict(
        severity="high",
        contour="physical",
        criticality=3,
        health=90,
        channels=1,
        opened_at=NIGHT,
        ack_deadline=NIGHT + timedelta(minutes=15),
        acknowledged=False,
        probability=None,
    )
    fresh, _ = priority(PriorityInput(**base, escalation_level=0, now=NIGHT))
    overdue, factors = priority(PriorityInput(**base, escalation_level=1, now=NIGHT + timedelta(minutes=20)))
    assert overdue > fresh and factors["urgency"] == 1.7
    forecast, _ = priority(PriorityInput(**(base | {"probability": 0.3}), escalation_level=0, now=NIGHT))
    assert forecast < fresh


def test_scale_raises_technical_severity(tree, channels):
    now = datetime.now(UTC)
    signals = [_signal(ch, "unknown", now, RiskLevel.LOW) for ch in channels[:12]]
    services.register_signals(
        type=IncidentType.SENSOR_FAILURE, node=tree["house"], source=Alert.Source.RULE, signals=signals
    )
    incident = Incident.objects.get()
    assert incident.type == IncidentType.COMMUNICATION and incident.severity == RiskLevel.HIGH


def test_likely_false_alarm_ranks_below_confirmed():
    base = dict(
        severity="critical",
        contour="physical",
        criticality=3,
        health=90,
        channels=1,
        opened_at=NIGHT,
        ack_deadline=None,
        acknowledged=False,
        probability=None,
        escalation_level=0,
        now=NIGHT,
    )
    likely_real, _ = priority(PriorityInput(**base, real_threat=0.8))
    likely_false, _ = priority(PriorityInput(**base, real_threat=0.2))
    assert likely_false < likely_real
