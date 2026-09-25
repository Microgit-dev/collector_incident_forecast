"""
Ядро симулятора: состояние каждого канала и поток сообщений в формате СМВУ.

Канал живёт сам: числовые датчики опрашиваются с шумом, дискретные периодически подтверждают
состояние. Поверх этого оператор или сценарий меняет режимы — тревога, неисправность, обесточивание,
молчание, плавный рост показаний, дребезг. Все изменения идут в приёмник (Kafka, консоль, файл)
теми же сообщениями, что отдаёт адаптер платформы: {event_id, channel_external_id, ts, raw_value,
raw_alarm, source}.

Время подставное (clock/wall), поэтому ядро проверяется тестами без ожиданий.
"""

from __future__ import annotations

import heapq
import itertools
import random
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .catalog import Catalog, Device
from .vocab import ALARM, EPOCH, FAULT, MODES, NORMAL, SENTINEL, SILENT

MOTION_PULSE_S = 15  # «Обнаружено движение» само сменяется «Движения нет»
RAMP_EMIT_S = 10  # во время плавного изменения показание отправляется чаще обычного


@dataclass
class ChannelState:
    mode: str = NORMAL
    level: float | None = None  # уставка числового датчика: вокруг неё идёт шум опроса
    value: float | None = None  # последнее отправленное показание
    op: bool | None = None
    ramp: tuple[float, float, float] | None = None  # (цель, изменение в секунду, период отправки)
    last_raw: str = ""
    last_alarm: bool | None = None
    last_sent: datetime | None = None
    next_poll: float = 0.0
    next_heartbeat: float = 0.0


@dataclass
class Step:
    delay_s: float
    title: str
    action: Callable[[], None]


@dataclass
class Run:
    id: int
    scenario: str
    title: str
    object_id: int
    speed: float
    started: datetime
    steps: list[Step]
    done: int = 0
    status: str = "running"  # running / done / stopped
    log: list[str] = field(default_factory=list)


class Engine:
    def __init__(
        self,
        catalog: Catalog,
        sink,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = lambda: datetime.now(UTC),
        seed: int | None = None,
        source: str = "simulator",
    ):
        self.catalog = catalog
        self.sink = sink
        self.clock = clock
        self.wall = wall
        self.source = source
        self.rng = random.Random(seed)
        self.lock = threading.RLock()
        self.channels: dict[int, ChannelState] = {}
        self.guard: dict[int, bool] = {}
        self.runs: dict[int, Run] = {}
        self.log: deque[dict] = deque(maxlen=300)
        self.sent = 0
        self.started = wall()
        self._tasks: list[tuple[float, int, Callable[[], None]]] = []
        self._seq = itertools.count()
        self._run_ids = itertools.count(1)
        self._event_id = int(time.time() * 1000) * 1000
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        now = clock()
        for device in catalog.devices.values():
            kind = device.kind
            state = ChannelState(
                level=kind.numeric[0] if kind.numeric else None,
                value=kind.numeric[0] if kind.numeric else None,
                op=False if kind.operation else None,
                next_poll=now + self.rng.uniform(0, kind.numeric[2]) if kind.numeric else 0.0,
                next_heartbeat=now + self.rng.uniform(0, kind.heartbeat_s),
            )
            self.channels[device.id] = state

    # ---------- отправка ----------

    def _emit(self, device: Device, raw: str, alarm: bool | None, ts: datetime | None = None) -> None:
        ts = ts or self.wall()
        self._event_id += 1
        message = {
            "event_id": self._event_id,
            "channel_external_id": device.id,
            "ts": ts.isoformat(),
            "raw_value": raw,
            "raw_alarm": alarm,
            "source": self.source,
        }
        self.sink.send(message)
        self.sent += 1
        state = self.channels[device.id]
        state.last_raw, state.last_alarm, state.last_sent = raw, alarm, ts
        self.log.appendleft(
            {"ts": ts.isoformat(), "channel": device.id, "name": device.name, "raw": raw, "alarm": alarm}
        )

    def _emit_numeric(self, device: Device, ts: datetime | None = None) -> None:
        state = self.channels[device.id]
        _, _, _, threshold = device.kind.numeric
        digits = 2 if threshold < 10 else 1
        self._emit(device, f"{state.value:.{digits}f}", state.value >= threshold, ts)

    def _emit_mode(self, device: Device, ts: datetime | None = None) -> None:
        state = self.channels[device.id]
        if state.mode == SILENT:
            return
        raw, alarm = device.kind.message(state.mode)
        if device.kind.guarded and state.mode == ALARM:
            # Охранный контакт тревожен только под охраной, иначе это рабочая активность
            alarm = self.guard.get(self.catalog.guard_zone(device), False)
        self._emit(device, raw, alarm, ts)
        if device.kind.numeric and state.mode in (NORMAL, ALARM):
            self._emit_numeric(device, ts)

    def announce(self) -> int:
        """Начальное состояние всех каналов: платформа сразу видит полигон «на связи»."""
        with self.lock:
            ts = self.wall()
            for device in self.catalog.devices.values():
                self._emit_mode(device, ts)
                state = self.channels[device.id]
                if state.op is not None:
                    self._emit(device, "Выключен", False, ts)
            for device in self.catalog.devices.values():
                if device.sensor_type == "Состояние охраны":
                    self._emit(device, "Снято с охраны", False, ts)
            self.sink.flush()
            return self.sent

    # ---------- действия оператора ----------

    def device(self, channel_id: int) -> Device:
        try:
            return self.catalog.devices[int(channel_id)]
        except KeyError:
            raise ValueError(f"нет канала {channel_id}") from None

    def set_mode(self, channel_id: int, mode: str, ts: datetime | None = None) -> None:
        device = self.device(channel_id)
        if mode not in MODES:
            raise ValueError(f"неизвестный режим {mode}; допустимы: {', '.join(MODES)}")
        with self.lock:
            state = self.channels[device.id]
            state.mode, state.ramp = mode, None
            if device.kind.numeric:
                base, _, _, threshold = device.kind.numeric
                if mode == NORMAL:
                    state.level = state.value = base
                elif mode == ALARM and (state.value or 0) < threshold:
                    state.level = state.value = round(threshold * 1.25, 2)
            self._emit_mode(device, ts)
            if device.kind.code == "motion" and mode == ALARM:
                self.schedule(MOTION_PULSE_S, lambda: self._motion_off(device.id))

    def _motion_off(self, channel_id: int) -> None:
        if self.channels[channel_id].mode == ALARM:
            self.set_mode(channel_id, NORMAL)

    def set_value(self, channel_id: int, value: float) -> None:
        device = self.device(channel_id)
        if not device.kind.numeric:
            raise ValueError(f"{device.name}: не числовой датчик")
        with self.lock:
            state = self.channels[device.id]
            state.ramp, state.level = None, float(value)
            self._apply_value(device, float(value))

    def _apply_value(self, device: Device, value: float) -> None:
        state = self.channels[device.id]
        threshold = device.kind.numeric[3]
        was_alarm = (state.value or 0) >= threshold
        state.value = value
        if state.mode in (NORMAL, ALARM):
            if value >= threshold and not was_alarm:
                state.mode = ALARM
                self._emit(device, *device.kind.message(ALARM))
            elif value < threshold and was_alarm:
                state.mode = NORMAL
                self._emit(device, *device.kind.message(NORMAL))
        self._emit_numeric(device)

    def ramp(self, channel_id: int, target: float, seconds: float) -> None:
        """Плавное изменение показания до цели за указанное время."""
        device = self.device(channel_id)
        if not device.kind.numeric:
            raise ValueError(f"{device.name}: не числовой датчик")
        with self.lock:
            state = self.channels[device.id]
            if state.mode not in (NORMAL, ALARM):
                state.mode = NORMAL
            seconds = max(float(seconds), 1.0)
            rate = (float(target) - (state.level or 0)) / seconds
            state.ramp = (float(target), rate, max(1.0, min(RAMP_EMIT_S, seconds / 12)))
            state.next_poll = self.clock()

    def set_op(self, channel_id: int, on: bool) -> None:
        device = self.device(channel_id)
        if not device.kind.operation:
            raise ValueError(f"{device.name}: не исполнительное устройство")
        with self.lock:
            self.channels[device.id].op = bool(on)
            self._emit(device, "Включен" if on else "Выключен", False)

    def set_guard(self, object_id: int, on: bool) -> None:
        """Поставить объект на охрану или снять: меняется и тревожность охранных контактов."""
        with self.lock:
            zones = self.catalog.guard_zones(int(object_id))
            if not zones:
                raise ValueError("у объекта нет охранной зоны")
            for zone in zones:
                self.guard[zone] = bool(on)
                for device in self.catalog.devices_under(zone):
                    if device.sensor_type == "Состояние охраны":
                        self._emit(device, "На охране" if on else "Снято с охраны", False)

    def send_raw(self, channel_id: int, raw: str, alarm: bool | None = None) -> None:
        """Произвольное значение как есть — например, служебный код или «битая» дата."""
        device = self.device(channel_id)
        with self.lock:
            self._emit(device, str(raw), alarm)

    def sentinel(self, channel_id: int) -> None:
        device = self.device(channel_id)
        with self.lock:
            self.channels[device.id].mode = FAULT
            self.channels[device.id].ramp = None
            self._emit(device, EPOCH if device.sensor_type == "Состояние охраны" else SENTINEL, False)

    def cascade(self, object_id: int, mode: str) -> int:
        """Все каналы объекта меняют состояние в одну секунду — как при потере питания шкафа."""
        with self.lock:
            ts = self.wall()
            devices = self.catalog.devices_under(int(object_id))
            for device in devices:
                self.set_mode(device.id, mode, ts)
            return len(devices)

    def flap(self, channel_id: int, times: int = 4, period_s: float = 20.0) -> None:
        """Дребезг: неисправность и восстановление чередуются, промежутки сокращаются."""
        device = self.device(channel_id)
        delay = 0.0
        for i in range(times):
            delay += period_s * (1 - i / (times + 1))
            self.schedule(delay, lambda: self.set_mode(device.id, FAULT))
            self.schedule(delay + period_s / 3, lambda: self.set_mode(device.id, NORMAL))

    def restore(self, object_id: int | None = None) -> int:
        """Всё под объектом (или весь каталог) — в норму, охрана снята, устройства выключены."""
        with self.lock:
            devices = self.catalog.devices_under(int(object_id)) if object_id else list(self.catalog.devices.values())
            ts = self.wall()
            for device in devices:
                state = self.channels[device.id]
                if (
                    state.mode != NORMAL
                    or state.ramp
                    or (device.kind.numeric and state.level != device.kind.numeric[0])
                ):
                    self.set_mode(device.id, NORMAL, ts)
                if state.op:
                    state.op = False
                    self._emit(device, "Выключен", False, ts)
            for zone in {self.catalog.guard_zone(d) for d in devices}:
                if self.guard.get(zone):
                    self.set_guard(zone, False)
            return len(devices)

    # ---------- сценарии ----------

    def start_scenario(self, name: str, object_id: int, picket: float | None = None, speed: float = 1.0) -> Run:
        from .scenarios import SCENARIOS

        if name not in SCENARIOS:
            raise ValueError(f"нет сценария {name}; есть: {', '.join(SCENARIOS)}")
        if int(object_id) not in self.catalog.objects:
            raise ValueError(f"нет объекта {object_id}")
        spec = SCENARIOS[name]
        speed = max(float(speed), 0.1)
        with self.lock:
            steps = spec.build(self, int(object_id), picket, speed)
            run = Run(
                id=next(self._run_ids),
                scenario=name,
                title=spec.title,
                object_id=int(object_id),
                speed=speed,
                started=self.wall(),
                steps=steps,
            )
            self.runs[run.id] = run
            elapsed = 0.0
            for index, step in enumerate(steps):
                elapsed += step.delay_s / speed
                self.schedule(elapsed, self._step_runner(run, index))
            if not steps:
                run.status = "done"
            return run

    def _step_runner(self, run: Run, index: int) -> Callable[[], None]:
        def execute():
            if run.status != "running":
                return
            step = run.steps[index]
            step.action()
            run.done = index + 1
            run.log.append(f"{self.wall():%H:%M:%S} {step.title}")
            if run.done == len(run.steps):
                run.status = "done"

        return execute

    def stop_run(self, run_id: int) -> None:
        with self.lock:
            run = self.runs.get(int(run_id))
            if run is None:
                raise ValueError(f"нет запуска {run_id}")
            if run.status == "running":
                run.status = "stopped"

    # ---------- планировщик ----------

    def schedule(self, delay_s: float, action: Callable[[], None]) -> None:
        with self.lock:
            heapq.heappush(self._tasks, (self.clock() + delay_s, next(self._seq), action))

    def tick(self) -> None:
        """Один шаг: отложенные действия, плавные изменения, опрос и подтверждение состояния."""
        with self.lock:
            now = self.clock()
            while self._tasks and self._tasks[0][0] <= now:
                _, _, action = heapq.heappop(self._tasks)
                action()
            for device_id, state in self.channels.items():
                if state.mode == SILENT:
                    continue
                device = self.catalog.devices[device_id]
                kind = device.kind
                if kind.numeric and state.mode in (NORMAL, ALARM) and now >= state.next_poll:
                    base, noise, period, _ = kind.numeric
                    if state.ramp:
                        target, rate, every = state.ramp
                        level = state.level + rate * every
                        if (rate >= 0 and level >= target) or (rate < 0 and level <= target):
                            level, state.ramp = target, None
                        state.level, value = level, level
                        state.next_poll = now + every
                    else:
                        value = state.level + self.rng.gauss(0, noise)
                        state.next_poll = now + period
                    self._apply_value(device, max(round(value, 2), 0.0) if base < 10 else round(value, 1))
                elif not kind.numeric and now >= state.next_heartbeat:
                    state.next_heartbeat = now + kind.heartbeat_s
                    if state.mode == NORMAL:
                        self._emit(device, *kind.message(NORMAL))
            self.sink.flush(0)

    def start(self, interval: float = 0.25) -> None:
        def loop():
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception as exc:  # цикл не должен падать из-за одной ошибки
                    self.log.appendleft({"ts": self.wall().isoformat(), "error": str(exc)})
                self._stop.wait(interval)

        self._thread = threading.Thread(target=loop, name="fieldsim", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.sink.flush()

    def wait_runs(self, poll: float = 0.25) -> None:
        while any(r.status == "running" for r in self.runs.values()) or any(s.ramp for s in self.channels.values()):
            time.sleep(poll)

    # ---------- снимок для интерфейса ----------

    def snapshot(self, object_id: int | None = None, limit_log: int = 100) -> dict:
        with self.lock:
            devices = self.catalog.devices_under(int(object_id)) if object_id else []
            channels = []
            for device in sorted(devices, key=lambda d: (d.object_id, d.picket or 0, d.name)):
                state = self.channels[device.id]
                kind = device.kind
                channels.append(
                    {
                        "id": device.id,
                        "name": device.name,
                        "type": device.sensor_type,
                        "object": self.catalog.objects[device.object_id].name
                        if device.object_id in self.catalog.objects
                        else "",
                        "picket": device.picket,
                        "mode": state.mode,
                        "mode_title": MODES[state.mode],
                        "value": state.value,
                        "level": state.level,
                        "ramp": state.ramp[0] if state.ramp else None,
                        "op": state.op,
                        "last_raw": state.last_raw,
                        "last_alarm": state.last_alarm,
                        "last_sent": state.last_sent.isoformat() if state.last_sent else None,
                        "modes": kind.modes,
                        "numeric": bool(kind.numeric),
                        "threshold": kind.numeric[3] if kind.numeric else None,
                        "operation": kind.operation,
                        "guarded": kind.guarded,
                    }
                )
            zones = sorted({self.catalog.guard_zone(d) for d in devices if d.kind.guarded})
            return {
                "started": self.started.isoformat(),
                "sent": self.sent,
                "sink": self.sink.status(),
                "channels": channels,
                "guard": [
                    {"object": z, "name": self.catalog.objects[z].name, "on": self.guard.get(z, False)}
                    for z in zones
                    if z in self.catalog.objects
                ],
                "runs": [
                    {
                        "id": r.id,
                        "scenario": r.scenario,
                        "title": r.title,
                        "object": self.catalog.objects[r.object_id].name,
                        "speed": r.speed,
                        "started": r.started.isoformat(),
                        "done": r.done,
                        "total": len(r.steps),
                        "status": r.status,
                        "log": r.log[-8:],
                        "next": r.steps[r.done].title if r.status == "running" and r.done < len(r.steps) else None,
                    }
                    for r in sorted(self.runs.values(), key=lambda r: -r.id)[:10]
                ],
                "log": list(itertools.islice(self.log, limit_log)),
            }
