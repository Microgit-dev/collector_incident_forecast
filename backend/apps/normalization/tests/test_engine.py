import pytest

from apps.normalization.domain.defaults import DEFAULT_SENTINELS, GLOBAL_RULES
from apps.normalization.domain.engine import Profile, Quality, State, ValueKind, normalize

GAS = Profile(
    code="gas_methane",
    value_kind=ValueKind.MIXED,
    valid_min=0,
    valid_max=100,
    warn_threshold=0.5,
    alarm_threshold=1.0,
    sentinels=frozenset(DEFAULT_SENTINELS),
)
DISCRETE = Profile(code="discrete", value_kind=ValueKind.STATE, sentinels=frozenset(DEFAULT_SENTINELS))


@pytest.mark.parametrize(
    ("raw", "state", "quality"),
    [
        ("0.02", State.NORMAL, Quality.OK),
        ("0,7", State.WARNING, Quality.OK),
        ("1.00", State.ALARM, Quality.OK),
        ("-100", State.FAULT, Quality.SENTINEL),
        ("255", State.FAULT, Quality.SENTINEL),
        ("-3", State.FAULT, Quality.OUT_OF_RANGE),
        ("01.01.1970 03:00:01", State.FAULT, Quality.EPOCH_ARTIFACT),
        ("", State.UNKNOWN, Quality.EMPTY),
    ],
)
def test_gas_numeric(raw, state, quality):
    result = normalize(raw, GAS, GLOBAL_RULES)
    assert (result.state, result.quality) == (state, quality)


@pytest.mark.parametrize(
    ("raw", "state", "facet"),
    [
        ("Норма", State.NORMAL, "primary"),
        ("Неисправен", State.FAULT, "primary"),
        ("Обесточен", State.POWER_LOSS, "power"),
        ("Обнаружен дым", State.ALARM, "primary"),
        ("Движение влево", State.ALARM, "primary"),
        ("Оба рычага сдернуты", State.ALARM, "primary"),
        ("Температура выше 35ºC1", State.ALARM, "temperature"),
        ("В норме от +3 до +27ºC", State.NORMAL, "temperature"),
        ("Неопределен", State.UNKNOWN, "primary"),
        ("Снято с охраны", State.EVENT, "guard"),
        ("Работают все насосы в АНС", State.ALARM, "pumps"),
    ],
)
def test_text_states(raw, state, facet):
    result = normalize(raw, DISCRETE, GLOBAL_RULES)
    assert (result.state, result.facet) == (state, facet)


def test_profile_rule_overrides_global():
    from apps.normalization.domain.engine import Rule

    door = Profile(code="door_nc", value_kind=ValueKind.STATE, rules=(Rule("Не замкнут", State.NORMAL),))
    assert normalize("Не замкнут", door, GLOBAL_RULES).state == State.NORMAL
    assert normalize("Не замкнут", DISCRETE, GLOBAL_RULES).state == State.ALARM


def test_unmapped_text_and_numeric_on_state_profile():
    assert normalize("Что-то новое", DISCRETE, GLOBAL_RULES).quality == Quality.UNMAPPED_TEXT
    assert normalize("12", DISCRETE, GLOBAL_RULES).quality == Quality.UNEXPECTED_NUMERIC
    assert normalize("-127", DISCRETE, GLOBAL_RULES).state == State.FAULT


def test_guarded_detection_is_activity_when_source_not_alarming():
    unguarded = normalize("Обнаружено движение", DISCRETE, GLOBAL_RULES, raw_alarm=False)
    assert (unguarded.state, unguarded.flags) == (State.EVENT, ("unguarded",))
    assert normalize("Обнаружено движение", DISCRETE, GLOBAL_RULES, raw_alarm=True).state == State.ALARM
    # Физическая угроза — тревога независимо от флага источника
    assert normalize("Обнаружен дым", DISCRETE, GLOBAL_RULES, raw_alarm=False).state == State.ALARM


def test_datetime_value_is_timestamp_event_but_1970_is_fault():
    stamp = normalize("22.09.2019 20:01:31", DISCRETE, GLOBAL_RULES)
    assert (stamp.state, stamp.facet) == (State.EVENT, "timestamp")
    assert normalize("01.01.1970 03:00:00", DISCRETE, GLOBAL_RULES).state == State.FAULT


def test_small_negative_gas_is_zero_drift_not_fault():
    gas = Profile(code="gas", value_kind=ValueKind.MIXED, valid_min=0, valid_max=100, drift_tolerance=0.1)
    drift = normalize("-0.03", gas, GLOBAL_RULES)
    assert (drift.state, drift.quality) == (State.NORMAL, Quality.DRIFT)
    assert normalize("-0.5", gas, GLOBAL_RULES).quality == Quality.OUT_OF_RANGE
