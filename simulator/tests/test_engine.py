from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fieldsim.catalog import Catalog, picket_of
from fieldsim.engine import Engine
from fieldsim.scenarios import SCENARIOS
from fieldsim.sinks import MemorySink

POLYGON = Path(__file__).resolve().parents[1] / "polygon"
MU, MU_FIRE, MU_GUARD, MU_CONTROL = 900100, 900101, 900102, 900103


class Clock:
    def __init__(self):
        self.t = 0.0
        self.start = datetime(2026, 9, 25, 12, tzinfo=UTC)

    def __call__(self):
        return self.t

    def wall(self):
        return self.start + timedelta(seconds=self.t)


@pytest.fixture
def sim():
    clock = Clock()
    sink = MemorySink()
    engine = Engine(Catalog.load(POLYGON), sink, clock=clock, wall=clock.wall, seed=1)
    return engine, sink, clock


def advance(engine, clock, seconds, step=1.0):
    end = clock.t + seconds
    while clock.t < end:
        clock.t += step
        engine.tick()


def by_name(engine, name, object_id=MU):
    return next(d for d in engine.catalog.devices_under(object_id) if d.name == name)


def test_picket_parsing():
    assert picket_of("ДД ПК204") == 204
    assert picket_of("Темп. ВШ ПК88,5") == 88.5
    assert picket_of("КД люк ПК745+1") == 745.1
    assert picket_of("ББП ДП") is None


def test_catalog_matches_platform_format():
    catalog = Catalog.load(POLYGON)
    assert len(catalog.objects) == 13 and len(catalog.devices) == 183
    assert catalog.picket_range(MU) == (200, 240)
    # у каждого объекта полигона есть всё, что нужно сценариям
    for complex_id in (900100, 900200, 900300):
        for spec in SCENARIOS.values():
            spec.build(Engine(catalog, MemorySink(), seed=0), complex_id, None, 1.0)


def test_message_contract(sim):
    engine, sink, _ = sim
    smoke = by_name(engine, "ДД ПК212")
    engine.set_mode(smoke.id, "alarm")
    message = sink.messages[-1]
    assert set(message) == {"event_id", "channel_external_id", "ts", "raw_value", "raw_alarm", "source"}
    assert message["raw_value"] == "Обнаружен дым" and message["raw_alarm"] is True
    assert datetime.fromisoformat(message["ts"]).tzinfo is not None


def test_guarded_contact_is_alarm_only_under_guard(sim):
    engine, sink, _ = sim
    door = by_name(engine, "КД дв.отс. ПК204")
    engine.set_mode(door.id, "alarm")
    assert (sink.messages[-1]["raw_value"], sink.messages[-1]["raw_alarm"]) == ("Не замкнут", False)
    engine.set_guard(MU, True)  # на охрану ставится весь объект — зона находится в его охранной части
    assert sink.messages[-1]["raw_value"] == "На охране"
    engine.set_mode(door.id, "normal")
    engine.set_mode(door.id, "alarm")
    assert sink.messages[-1]["raw_alarm"] is True


def test_motion_is_a_pulse(sim):
    engine, sink, clock = sim
    motion = by_name(engine, "ОД ПК204")
    engine.set_mode(motion.id, "alarm")
    advance(engine, clock, 20)
    raws = [m["raw_value"] for m in sink.messages if m["channel_external_id"] == motion.id]
    assert raws == ["Обнаружено движение", "Движения нет"]


def test_gas_threshold_crossing_sends_state_text(sim):
    engine, sink, clock = sim
    gas = by_name(engine, "ГАЗ Д2 ПК208")
    engine.ramp(gas.id, 1.4, 60)
    advance(engine, clock, 90)
    own = [m for m in sink.messages if m["channel_external_id"] == gas.id]
    assert "Обнаружен газ" in [m["raw_value"] for m in own]
    numeric = [float(m["raw_value"]) for m in own if m["raw_value"][0].isdigit()]
    ramp = numeric[: numeric.index(1.4) + 1]  # дальше — обычный опрос с шумом вокруг 1,4
    assert ramp == sorted(ramp) and len(ramp) > 5
    assert engine.channels[gas.id].mode == "alarm"


def test_cascade_is_one_timestamp(sim):
    engine, sink, _ = sim
    count = engine.cascade(MU_FIRE, "power")
    batch = sink.messages[-count:]
    assert count == len(engine.catalog.devices_under(MU_FIRE))
    assert len({m["ts"] for m in batch}) == 1
    assert {m["raw_value"] for m in batch} == {"Обесточен"}


def test_silent_channel_sends_nothing(sim):
    engine, sink, clock = sim
    gas = by_name(engine, "ГАЗ Д1 ПК200")
    engine.set_mode(gas.id, "silent")
    before = len(sink.messages)
    advance(engine, clock, 600, step=10)
    assert not [m for m in sink.messages[before:] if m["channel_external_id"] == gas.id]


def test_polling_keeps_numeric_channels_alive(sim):
    engine, sink, clock = sim
    advance(engine, clock, 130, step=5)
    gas_ids = {d.id for d in engine.catalog.devices.values() if d.sensor_type == "Газовый датчик"}
    assert gas_ids <= {m["channel_external_id"] for m in sink.messages}
    assert all(m["raw_alarm"] is False for m in sink.messages)  # шум нормы не даёт тревог


def test_scenario_runs_in_order_with_speed(sim):
    engine, sink, clock = sim
    run = engine.start_scenario("fire", MU, 212, speed=10)
    advance(engine, clock, 30)
    assert run.status == "done" and run.done == len(run.steps)
    raws = [m["raw_value"] for m in sink.messages]
    assert raws.index("Обнаружен дым") < raws.index("Не замкнут")
    temp_id = by_name(engine, "Темп. ВШ ПК208").id
    temps = [
        float(m["raw_value"])
        for m in sink.messages
        if m["channel_external_id"] == temp_id and m["raw_value"][0].isdigit()
    ]
    assert max(temps) == 52  # рост температуры ускорен вместе со сценарием


def test_stop_run(sim):
    engine, sink, clock = sim
    run = engine.start_scenario("intrusion", MU, None, speed=1)
    advance(engine, clock, 5)
    engine.stop_run(run.id)
    advance(engine, clock, 300, step=5)
    assert run.status == "stopped" and run.done < len(run.steps)


def test_restore_returns_everything(sim):
    engine, _, clock = sim
    engine.start_scenario("flood", MU, None, speed=30)
    engine.set_guard(MU, True)
    advance(engine, clock, 30)
    engine.restore(MU)
    states = [engine.channels[d.id] for d in engine.catalog.devices_under(MU)]
    assert all(s.mode == "normal" and not s.op for s in states)
    assert not any(engine.guard.values())


def test_flap_alternates(sim):
    engine, sink, clock = sim
    smoke = by_name(engine, "ДД ПК200")
    engine.flap(smoke.id, times=3, period_s=10)
    advance(engine, clock, 60)
    raws = [m["raw_value"] for m in sink.messages if m["channel_external_id"] == smoke.id]
    assert raws == ["Неисправен", "Норма"] * 3


def test_errors_are_value_errors(sim):
    engine, *_ = sim
    with pytest.raises(ValueError):
        engine.set_mode(1, "alarm")
    with pytest.raises(ValueError):
        engine.set_value(by_name(engine, "ДД ПК200").id, 5)
    with pytest.raises(ValueError):
        engine.start_scenario("nope", MU)


def test_training_commands(sim):
    from fieldsim.commands import handle

    engine, sink, clock = sim
    assert handle(engine, {"op": "scenario", "scenario": "fire", "object": MU, "picket": 220, "speed": 10}).startswith(
        "запуск #1"
    )
    advance(engine, clock, 30)
    assert engine.channels[by_name(engine, "ДД ПК220").id].mode == "alarm"
    handle(engine, {"op": "restore", "object": MU})
    assert engine.channels[by_name(engine, "ДД ПК220").id].mode == "normal"
    with pytest.raises(ValueError):
        handle(engine, {"op": "drop-tables"})


def test_restore_command_stops_the_scenario(sim):
    """Досрочная остановка учений: после restore оставшиеся шаги сценария не срабатывают."""
    from fieldsim.commands import handle

    engine, sink, clock = sim
    run = engine.start_scenario("intrusion", MU, None, speed=1)
    advance(engine, clock, 35)  # охрана и вскрытый люк
    assert "остановлено сценариев: 1" in handle(engine, {"op": "restore", "object": MU})
    advance(engine, clock, 300, step=5)
    assert run.status == "stopped"
    assert all(engine.channels[d.id].mode == "normal" for d in engine.catalog.devices_under(MU))


def _alarms(engine, sink):
    names = {d.id: d.name for d in engine.catalog.devices_under(MU)}
    return [names.get(m["channel_external_id"]) for m in sink.messages if m["raw_alarm"] is True]


def test_intruder_walks_along_pickets(sim):
    engine, sink, clock = sim
    run = engine.start_scenario("intrusion", MU, 200, speed=30)
    advance(engine, clock, 60)
    assert run.status == "done"
    walk = [n for n in _alarms(engine, sink) if n and ("ОД" in n or "КД" in n)]
    assert walk[0] == "КД люк ПК200"
    pickets = [picket_of(n) for n in walk]
    assert pickets == sorted(pickets) and len(walk) >= 5  # идёт от люка вглубь коллектора


def test_temperature_without_smoke(sim):
    engine, sink, clock = sim
    engine.start_scenario("temperature", MU, 216, speed=30)
    advance(engine, clock, 60)
    alarms = _alarms(engine, sink)
    assert "Температура выше 40ºC" in [m["raw_value"] for m in sink.messages]
    assert all("ДД" not in (n or "") for n in alarms)


def test_ppr_checks_detectors_one_by_one(sim):
    engine, sink, clock = sim
    run = engine.start_scenario("ppr", MU, 204, speed=30)
    advance(engine, clock, 60)
    assert run.status == "done"
    smoke = [m["raw_value"] for m in sink.messages if m["raw_value"] in ("Обнаружен дым", "Норма")]
    assert smoke.count("Обнаружен дым") >= 5
    # каждая проверка сразу сбрасывается: после дыма — норма того же извещателя
    assert all(engine.channels[d.id].mode == "normal" for d in engine.catalog.find(MU, "Датчик дыма", 204, 6))
