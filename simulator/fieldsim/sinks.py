"""Куда уходят сообщения: Kafka (как у настоящей СМВУ), консоль или файл JSON Lines."""

from __future__ import annotations

import json
import sys
import threading


class MemorySink:
    """Для тестов: сообщения копятся в списке."""

    def __init__(self):
        self.messages: list[dict] = []

    def send(self, message: dict) -> None:
        self.messages.append(message)

    def flush(self, timeout: float | None = None) -> None:
        pass

    def status(self) -> dict:
        return {"kind": "memory", "target": "", "errors": 0}


class StreamSink:
    def __init__(self, stream=None, target: str = "stdout"):
        self.stream = stream or sys.stdout
        self.target = target
        self._lock = threading.Lock()

    def send(self, message: dict) -> None:
        with self._lock:
            self.stream.write(json.dumps(message, ensure_ascii=False) + "\n")

    def flush(self, timeout: float | None = None) -> None:
        self.stream.flush()

    def status(self) -> dict:
        return {"kind": "file" if self.target != "stdout" else "stdout", "target": self.target, "errors": 0}


class KafkaSink:
    def __init__(self, bootstrap: str, topic: str):
        from confluent_kafka import Producer

        self.topic = topic
        self.bootstrap = bootstrap
        self.errors = 0
        self.delivered = 0
        self.last_error = ""
        self._producer = Producer(
            {
                "bootstrap.servers": bootstrap,
                "linger.ms": 50,
                "compression.type": "lz4",
                "enable.idempotence": True,
                "error_cb": self._on_error,
            }
        )

    def _on_error(self, error) -> None:
        self.last_error = str(error)

    def _on_delivery(self, error, _msg) -> None:
        if error is not None:
            self.errors += 1
            self.last_error = str(error)
        else:
            self.delivered += 1
            self.last_error = ""

    def send(self, message: dict) -> None:
        # Ключ = канал: события одного канала попадают в одну партицию и сохраняют порядок
        self._producer.produce(
            self.topic,
            key=str(message["channel_external_id"]),
            value=json.dumps(message, ensure_ascii=False).encode(),
            on_delivery=self._on_delivery,
        )
        self._producer.poll(0)

    def flush(self, timeout: float | None = None) -> None:
        if timeout == 0:
            self._producer.poll(0)
        else:
            self._producer.flush(timeout if timeout is not None else 10)

    def status(self) -> dict:
        return {
            "kind": "kafka",
            "target": f"{self.bootstrap} → {self.topic}",
            "delivered": self.delivered,
            "errors": self.errors,
            "last_error": self.last_error,
        }


def make_sink(spec: str, bootstrap: str, topic: str):
    """stdout | file:путь | kafka"""
    if spec == "kafka":
        return KafkaSink(bootstrap, topic)
    if spec == "stdout":
        return StreamSink()
    if spec.startswith("file:"):
        path = spec.removeprefix("file:")
        return StreamSink(open(path, "a", encoding="utf-8"), path)  # noqa: SIM115 — живёт до конца процесса
    raise ValueError(f"неизвестный приёмник {spec}: stdout, file:путь или kafka")
