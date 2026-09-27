"""
Эмулятор системы видеонаблюдения заказчика (VMS) для проверки тревоги по камерам (ТЗ §12, шаг 4).
Без зависимостей: стандартная библиотека Python.

Кадр — синтетическое изображение (SVG) тоннеля коллектора с подписью камеры и временем кадра, как
у настоящего архива VMS. Сцена детерминирована камерой и часом: повторный запрос того же момента
даёт тот же кадр. Настоящая VMS отдаёт JPEG по тому же контракту.

API:
  GET /health                               проверка связи
  GET /api/cameras/<id>/snapshot?at=ISO      кадр на момент из архива (без at — текущий)
  GET /vms/live/<id>?at=ISO                  страница просмотра («поток»): кадр обновляется раз в 2 с
"""

from __future__ import annotations

import hashlib
import html
import os
import random
from datetime import UTC, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

MSK = timezone(timedelta(hours=3))


def _moment(value: str | None) -> tuple[datetime, bool]:
    if value:
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            return moment, True
        except ValueError:
            pass
    return datetime.now(UTC), False


def frame(camera: str, at: datetime, archive: bool) -> str:
    """SVG-кадр: перспектива тоннеля, лотки с кабелями, светильники, шум матрицы, штамп времени."""
    seed = int(hashlib.sha256(f"{camera}:{at:%Y%m%d%H}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    night = at.astimezone(MSK).hour in range(0, 6)
    wall = "#2b2f33" if night else "#3a3f44"
    lamps = "".join(
        f'<ellipse cx="{320 + (i - 2) * 6}" cy="{70 + i * 18}" rx="{18 - i * 3}" ry="{4 - i * 0.6:.1f}" fill="#fff6c8" opacity="{0.9 - i * 0.15:.2f}"/>'
        for i in range(5)
    )
    trays = "".join(
        f'<line x1="{x1}" y1="{y}" x2="{320 + (x1 - 320) * 0.12:.0f}" y2="{180 + (y - 180) * 0.12:.0f}" stroke="{c}" stroke-width="{w}"/>'
        for x1, y, c, w in [
            (0, 150, "#555", 6),
            (0, 200, "#444", 5),
            (640, 150, "#555", 6),
            (640, 200, "#444", 5),
            (0, 250, "#6b5a2e", 3),
            (640, 250, "#2e4d6b", 3),
        ]
    )
    noise = "".join(
        f'<rect x="{rng.randrange(640)}" y="{rng.randrange(360)}" width="2" height="2" fill="#fff" opacity="{rng.random() * 0.25:.2f}"/>'
        for _ in range(160)
    )
    # иногда в кадре обходчик — чтобы архив отличался от текущего кадра
    person = (
        f'<g transform="translate({rng.randrange(260, 380)},{rng.randrange(215, 235)})" fill="#e0a526">'
        '<circle cx="0" cy="0" r="7"/><rect x="-7" y="8" width="14" height="30" rx="3"/></g>'
        if rng.random() < 0.25 and not night
        else ""
    )
    stamp = at.astimezone(MSK).strftime("%d.%m.%Y %H:%M:%S")
    mode = "АРХИВ" if archive else "ПРЯМОЙ ЭФИР"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360" width="640" height="360">
<rect width="640" height="360" fill="{wall}"/>
<polygon points="0,0 640,0 360,150 280,150" fill="#24282b"/>
<polygon points="0,360 640,360 360,210 280,210" fill="#4a4a44"/>
<rect x="280" y="150" width="80" height="60" fill="#15181a"/>
{lamps}{trays}{person}{noise}
<rect x="0" y="0" width="640" height="26" fill="#000" opacity="0.55"/>
<text x="10" y="18" font-family="monospace" font-size="14" fill="#fff">{html.escape(camera)}</text>
<text x="630" y="18" font-family="monospace" font-size="14" fill="#fff" text-anchor="end">{stamp}</text>
<text x="10" y="350" font-family="monospace" font-size="12" fill="{'#ffb347' if archive else '#7CFC00'}">● {mode} · эмуляция VMS</text>
</svg>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        parts = [unquote(p) for p in url.path.split("/") if p]
        query = parse_qs(url.query)
        at_raw = query.get("at", [None])[0]
        # через Caddy страница просмотра открывается под /vms/: /vms/api/... — то же API
        if parts[:1] == ["vms"] and parts[1:2] != ["live"]:
            parts = parts[1:]
        if parts == ["health"]:
            return self._send(b'{"status": "ok"}', "application/json")
        if len(parts) == 4 and parts[:2] == ["api", "cameras"] and parts[3] == "snapshot":
            moment, archive = _moment(at_raw)
            return self._send(frame(parts[2], moment, archive).encode(), "image/svg+xml; charset=utf-8")
        if len(parts) == 3 and parts[:2] == ["vms", "live"]:
            return self._live(parts[2], at_raw)
        return self._send(b'{"detail": "not found"}', "application/json", 404)

    def _live(self, camera: str, at_raw: str | None) -> None:
        cam = html.escape(camera)
        archive = f"<p>Архив на момент тревоги:</p><img src='/vms/api/cameras/{quote(camera)}/snapshot?at={quote(at_raw)}'>" if at_raw else ""
        page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Камера {cam} (эмуляция)</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;background:#111;color:#eee}}img{{max-width:100%;border:1px solid #333}}</style>
</head><body><h3>Камера {cam} — система видеонаблюдения (эмуляция)</h3>
<p>Прямой эфир:</p><img id="live" src="/vms/api/cameras/{quote(camera)}/snapshot">
{archive}
<script>setInterval(function(){{document.getElementById('live').src='/vms/api/cameras/{quote(camera)}/snapshot?t='+Date.now()}},2000)</script>
</body></html>"""
        self._send(page.encode(), "text/html; charset=utf-8")

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"mock VMS on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
