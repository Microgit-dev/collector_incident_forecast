"""
Команды из учебного контура: платформа не видит симулятор по сети (полевой контур), поэтому урок
просит «восстановить объект» и «запустить сценарий» через ту же Kafka, в которую симулятор пишет события.
Читаются только новые команды (latest): после перезапуска симулятор не повторяет старые уроки.
"""

from __future__ import annotations

import json
import logging
import threading

from .engine import Engine

logger = logging.getLogger("fieldsim.commands")


def handle(engine: Engine, command: dict) -> str:
    """Выполнить одну команду; ошибка ввода — ValueError."""
    op = command.get("op")
    obj = int(command["object"]) if command.get("object") is not None else None
    if op == "restore":
        # сначала остановить сценарии объекта, иначе их оставшиеся шаги снова поднимут тревоги
        stopped = engine.stop_runs(obj)
        return f"остановлено сценариев: {stopped}, восстановлено каналов: {engine.restore(obj)}"
    if op == "scenario":
        picket = command.get("picket")
        run = engine.start_scenario(
            command["scenario"], obj, float(picket) if picket is not None else None, float(command.get("speed") or 1)
        )
        return f"запуск #{run.id} {run.title}"
    if op == "guard":
        engine.set_guard(obj, bool(command.get("on")))
        return "охрана"
    raise ValueError(f"неизвестная команда {op}")


def listen(engine: Engine, bootstrap: str, topic: str, stop: threading.Event) -> None:
    from confluent_kafka import Consumer

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": "fieldsim-commands",
            "auto.offset.reset": "latest",
            "allow.auto.create.topics": True,
        }
    )
    consumer.subscribe([topic])
    logger.info("commands: %s", topic)
    try:
        while not stop.is_set():
            msg = consumer.poll(1.0)
            if msg is None or msg.error():
                continue
            try:
                command = json.loads(msg.value())
                result = handle(engine, command)
                logger.info("command %s: %s", command, result)
                engine.log.appendleft({"ts": engine.wall().isoformat(), "command": f"{command.get('op')}: {result}"})
            except (ValueError, KeyError, TypeError) as exc:
                logger.warning("bad command %s: %s", msg.value()[:200], exc)
                engine.log.appendleft({"ts": engine.wall().isoformat(), "error": f"команда: {exc}"})
    finally:
        consumer.close()


def start_listener(engine: Engine, bootstrap: str, topic: str) -> threading.Event:
    stop = threading.Event()
    threading.Thread(
        target=listen, args=(engine, bootstrap, topic, stop), name="fieldsim-commands", daemon=True
    ).start()
    return stop
