"""
Веб-интерфейс и JSON API симулятора (стандартная библиотека). Консольный клиент ходит в тот же API,
поэтому всё, что можно сделать мышью, можно сделать и из скрипта.
"""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .engine import Engine
from .scenarios import SCENARIOS
from .vocab import MODES

STATIC = Path(__file__).parent / "static"
logger = logging.getLogger("fieldsim.web")


def _bool(value) -> bool:
    return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")


def perform(engine: Engine, body: dict) -> dict:
    """Одно действие оператора; ошибки ввода — ValueError."""
    op = body.get("op")
    channel, obj = body.get("channel"), body.get("object")
    if op == "mode":
        engine.set_mode(channel, body["mode"])
    elif op == "value":
        engine.set_value(channel, float(body["value"]))
    elif op == "ramp":
        engine.ramp(channel, float(body["target"]), float(body.get("seconds", 120)))
    elif op == "op":
        engine.set_op(channel, _bool(body["on"]))
    elif op == "guard":
        engine.set_guard(obj, _bool(body["on"]))
    elif op == "raw":
        alarm = body.get("alarm")
        engine.send_raw(channel, body["raw"], None if alarm in (None, "") else _bool(alarm))
    elif op == "sentinel":
        engine.sentinel(channel)
    elif op == "cascade":
        return {"channels": engine.cascade(obj, body["mode"])}
    elif op == "flap":
        engine.flap(channel, int(body.get("times", 4)), float(body.get("period", 20)))
    elif op == "restore":
        return {"channels": engine.restore(obj)}
    else:
        raise ValueError(f"неизвестное действие {op}")
    return {"ok": True}


def make_handler(engine: Engine, contour: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "fieldsim"

        def log_message(self, fmt, *args):
            logger.debug(fmt, *args)

        def _json(self, payload, status=HTTPStatus.OK):
            data = json.dumps(payload, ensure_ascii=False, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}") if length else {}

        def do_GET(self):
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/health":
                return self._json({"status": "ok"})
            if url.path in ("/", "/index.html"):
                data = (STATIC / "index.html").read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            if url.path == "/api/meta":
                return self._json(
                    {
                        "contour": contour,
                        "tree": engine.catalog.tree(),
                        "modes": MODES,
                        "scenarios": [
                            {
                                "code": s.code,
                                "title": s.title,
                                "description": s.description,
                                "uses_picket": s.uses_picket,
                            }
                            for s in SCENARIOS.values()
                        ],
                    }
                )
            if url.path == "/api/state":
                obj = query.get("object")
                return self._json(engine.snapshot(int(obj) if obj else None))
            return self._json({"detail": "не найдено"}, HTTPStatus.NOT_FOUND)

        def do_POST(self):
            url = urlparse(self.path)
            try:
                body = self._body()
                if url.path == "/api/action":
                    return self._json(perform(engine, body))
                if url.path == "/api/scenario":
                    picket = body.get("picket")
                    run = engine.start_scenario(
                        body["scenario"],
                        int(body["object"]),
                        float(picket) if picket not in (None, "") else None,
                        float(body.get("speed") or 1),
                    )
                    return self._json({"id": run.id, "steps": [s.title for s in run.steps]}, HTTPStatus.CREATED)
                if url.path.startswith("/api/scenario/") and url.path.endswith("/stop"):
                    engine.stop_run(int(url.path.split("/")[3]))
                    return self._json({"ok": True})
            except (ValueError, KeyError, TypeError) as exc:
                return self._json({"detail": str(exc)}, HTTPStatus.BAD_REQUEST)
            return self._json({"detail": "не найдено"}, HTTPStatus.NOT_FOUND)

    return Handler


def serve(engine: Engine, host: str, port: int, contour: str) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(engine, contour))
    server.daemon_threads = True
    logger.info("web: http://%s:%s", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
