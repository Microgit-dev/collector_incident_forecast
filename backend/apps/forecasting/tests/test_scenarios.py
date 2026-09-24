from datetime import UTC, datetime

from apps.forecasting.domain.scenarios import ChannelWindow, ScenarioContext, fire_risk, intrusion_risk, level

NIGHT = datetime(2026, 6, 30, 2, 0, tzinfo=UTC)
DAY = datetime(2026, 6, 30, 11, 0, tzinfo=UTC)


def test_single_flaky_smoke_detector_is_low_risk():
    smoke = ChannelWindow(1, "Датчик дыма", "Дым ПК10", picket=10, alarms=4, fault_history=8)
    risk = fire_risk([smoke], ScenarioContext(local_time=NIGHT))
    assert level(risk.score) == "low"
    assert any("ненадёжны" in f["title"] for f in risk.factors)


def test_confirmed_fire_by_neighbours_and_temperature_is_critical():
    channels = [
        ChannelWindow(1, "Датчик дыма", "Дым ПК10", picket=10, alarms=1, health=95),
        ChannelWindow(2, "Датчик дыма", "Дым ПК11", picket=11, alarms=1, health=95),
        ChannelWindow(
            3, "Датчик температуры", "Темп ПК10+5", picket=10.5, numeric_now=31.0, numeric_base=18.0
        ),
    ]
    risk = fire_risk(channels, ScenarioContext(local_time=NIGHT))
    assert level(risk.score) == "critical" and risk.channel_id == 1
    titles = " ".join(f["title"] for f in risk.factors)
    assert "Рост температуры на 13.0" in titles and "подтверждают друг друга" in titles


def test_intrusion_at_night_on_armed_object_vs_authorized_access():
    channels = [
        ChannelWindow(1, "КД Дверь", "Дверь ПК5", alarms=2),
        ChannelWindow(2, "Датчик движения", "Движение ПК5", alarms=2),
    ]
    armed_night = intrusion_risk(channels, ScenarioContext(local_time=NIGHT, guard_armed=True))
    authorized = intrusion_risk(
        channels, ScenarioContext(local_time=DAY, guard_armed=True, works_in_progress=1)
    )
    assert level(armed_night.score) == "critical"
    assert level(authorized.score) in ("low", "medium")
    assert any("санкционированный" in f["title"] for f in authorized.factors)
    assert intrusion_risk([], ScenarioContext(local_time=NIGHT)).score == 0
