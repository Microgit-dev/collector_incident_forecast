"""
Эмулятор системы учёта заявок заказчика (help desk на Django, ТЗ §6, §10). Без зависимостей:
стандартная библиотека Python и SQLite.

Жизненный цикл заявки: принята → назначена бригада → в работе → выполнена (с отчётом) → закрыта.
Стадии идут сами по времени от создания (STAGE_MINUTES, для критических — вдвое быстрее), для демонстрации
заявку можно продвинуть вручную: POST /api/tickets/<id>/advance/.

API:
  POST /api/tickets/                  создать заявку → {"id": "HD-000001", ...}
  GET  /api/tickets/                  список
  GET  /api/tickets/<id>/             заявка с историей
  GET  /api/tickets/statuses/?ids=a,b статусы пачкой (так их забирает система прогнозирования)
  POST /api/tickets/<id>/advance/     следующая стадия сейчас
  GET  /                              страница со списком заявок (вид «со стороны help desk»)
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DB = os.environ.get("HELPDESK_DB", "/data/helpdesk.sqlite3")
# минуты до перехода: принята→назначена, назначена→в работе, в работе→выполнена, выполнена→закрыта
STAGE_MINUTES = [float(x) for x in os.environ.get("STAGE_MINUTES", "2,5,20,10").split(",")]
STAGES = ["accepted", "assigned", "in_progress", "done", "closed"]
LABELS = {
    "accepted": "Принята",
    "assigned": "Назначена бригада",
    "in_progress": "В работе",
    "done": "Выполнена",
    "closed": "Закрыта",
}
BRIGADES = [
    "Бригада №1 (Смирнов С.)",
    "Бригада №2 (Попов А.)",
    "Бригада №3 (Егоров Н.)",
    "Бригада охраны и связи (Кравцов В.)",
    "Электротехническая бригада (Лебедев М.)",
]
REPORTS = {
    "inspection": "Проведён осмотр. Неисправностей оборудования не выявлено, показания в норме.",
    "sensor_replacement": "Датчик демонтирован и заменён на исправный, выполнена проверка срабатывания.",
    "calibration": "Сигнализатор откалиброван поверочной смесью, погрешность в пределах нормы.",
    "power_check": "Проверены ввод и автоматы шкафа, подтянуты контакты, питание стабильно.",
    "pump_service": "Насосы АНС обслужены: очищены приямки, проверены поплавки и пуск насосов.",
    "ventilation": "Вентиляция проверена, фильтры очищены, производительность в норме.",
    "cleaning": "Выполнена откачка воды и очистка лотка, дренаж восстановлен.",
    "security": "Периметр проверен, датчики доступа исправны, следов проникновения нет.",
}
PRIORITY = {"critical": "критический", "high": "высокий", "medium": "средний", "low": "низкий"}
lock = threading.Lock()


def now() -> datetime:
    return datetime.now(UTC)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
    with db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS ticket (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                manual_stage INTEGER NOT NULL DEFAULT 0,
                manual_at TEXT
            )"""
        )


def schedule(created: datetime, priority: str) -> list[datetime]:
    """Моменты входа в каждую стадию; критические идут вдвое быстрее, низкие — вдвое медленнее."""
    factor = {"critical": 0.5, "high": 0.75, "medium": 1.0, "low": 2.0}.get(priority, 1.0)
    moments, t = [created], created
    for minutes in STAGE_MINUTES:
        t = t + timedelta(minutes=minutes * factor)
        moments.append(t)
    return moments


def render(row: sqlite3.Row) -> dict:
    payload = json.loads(row["payload"])
    created = datetime.fromisoformat(row["created_at"])
    moments = schedule(created, payload.get("priority", "medium"))
    current = now()
    stage = max(i for i, t in enumerate(moments) if t <= current)
    if row["manual_stage"] > stage:
        # вручную продвинутые стадии: всё, что не наступило по времени, — на момент продвижения
        manual_at = datetime.fromisoformat(row["manual_at"])
        moments = [t if i <= stage else min(t, manual_at) for i, t in enumerate(moments)]
        stage = row["manual_stage"]
    ticket_id = f"HD-{row['seq']:06d}"
    brigade = _brigade(payload, ticket_id) if stage >= 1 else None
    status = STAGES[stage]
    return {
        "id": ticket_id,
        "number": payload.get("number"),
        "title": payload.get("title"),
        "priority": payload.get("priority"),
        "work_type": payload.get("work_type"),
        "node": payload.get("node"),
        "due_at": payload.get("due_at"),
        "status": status,
        "status_label": LABELS[status],
        "assignee": brigade,
        "report": REPORTS.get(payload.get("work_type"), "Работы выполнены.") if stage >= 3 else "",
        "created_at": created.isoformat(),
        "updated_at": moments[stage].isoformat(),
        "history": [
            {"status": STAGES[i], "label": LABELS[STAGES[i]], "at": moments[i].isoformat()} for i in range(stage + 1)
        ],
    }


def _brigade(payload: dict, ticket_id: str) -> str:
    """Профильная бригада по виду работ, остальные — одна из линейных бригад."""
    special = {"power_check": BRIGADES[4], "security": BRIGADES[3]}
    if payload.get("work_type") in special:
        return special[payload["work_type"]]
    digest = int(hashlib.md5((payload.get("node") or ticket_id).encode()).hexdigest(), 16)
    return BRIGADES[digest % 3]


def fetch(ticket_id: str) -> sqlite3.Row | None:
    try:
        seq = int(ticket_id.removeprefix("HD-"))
    except ValueError:
        return None
    with db() as conn:
        return conn.execute("SELECT * FROM ticket WHERE seq = ?", (seq,)).fetchone()


class Handler(BaseHTTPRequestHandler):
    server_version = "MockHelpdesk/1.0"

    def _json(self, body, status: int = 200) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        if url.path in ("/health", "/health/"):
            return self._json({"status": "ok"})
        if parts == ["api", "tickets", "statuses"]:
            ids = [i for i in parse_qs(url.query).get("ids", [""])[0].split(",") if i]
            out = {}
            for ticket_id in ids:
                row = fetch(ticket_id)
                if row:
                    out[ticket_id] = render(row)
            return self._json(out)
        if parts == ["api", "tickets"]:
            with db() as conn:
                rows = conn.execute("SELECT * FROM ticket ORDER BY seq DESC LIMIT 500").fetchall()
            return self._json([render(r) for r in rows])
        if len(parts) == 3 and parts[:2] == ["api", "tickets"]:
            row = fetch(parts[2])
            return self._json(render(row)) if row else self._json({"detail": "not found"}, 404)
        if not parts or parts == ["helpdesk"]:
            return self._page()
        return self._json({"detail": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if parts == ["api", "tickets"]:
            payload = self._body()
            if not payload.get("title"):
                return self._json({"detail": "title required"}, 400)
            with lock, db() as conn:
                cur = conn.execute(
                    "INSERT INTO ticket (created_at, payload) VALUES (?, ?)",
                    (now().isoformat(), json.dumps(payload, ensure_ascii=False)),
                )
                row = conn.execute("SELECT * FROM ticket WHERE seq = ?", (cur.lastrowid,)).fetchone()
            return self._json(render(row), 201)
        if len(parts) == 4 and parts[:2] == ["api", "tickets"] and parts[3] == "advance":
            row = fetch(parts[2])
            if not row:
                return self._json({"detail": "not found"}, 404)
            current = STAGES.index(render(row)["status"])
            with lock, db() as conn:
                conn.execute(
                    "UPDATE ticket SET manual_stage = ?, manual_at = ? WHERE seq = ?",
                    (min(current + 1, len(STAGES) - 1), now().isoformat(), row["seq"]),
                )
            if "redirect" in urlparse(self.path).query:
                self.send_response(303)
                self.send_header("Location", "/helpdesk/")
                self.end_headers()
                return None
            return self._json(render(fetch(parts[2])))
        return self._json({"detail": "not found"}, 404)

    def _page(self):
        with db() as conn:
            rows = [render(r) for r in conn.execute("SELECT * FROM ticket ORDER BY seq DESC LIMIT 200")]
        lines = "".join(
            f"<tr><td>{t['id']}</td><td>{html.escape(t['number'] or '')}</td><td>{html.escape(t['title'] or '')}</td>"
            f"<td>{html.escape(t['node'] or '')}</td><td>{PRIORITY.get(t['priority'], t['priority'])}</td>"
            f"<td><b>{t['status_label']}</b></td>"
            f"<td>{html.escape(t['assignee'] or '—')}</td><td>{t['updated_at'][:16].replace('T', ' ')}</td>"
            + (
                f"<td><form method=post action='/helpdesk/api/tickets/{t['id']}/advance/?redirect=1'>"
                "<button>Следующая стадия</button></form></td></tr>"
                if t["status"] != "closed"
                else "<td></td></tr>"
            )
            for t in rows
        )
        page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta http-equiv="refresh" content="15">
<title>Help desk (эмуляция)</title><style>body{{font-family:system-ui,sans-serif;margin:24px;color:#222}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left;font-size:14px}}
th{{background:#f3f4f7}}.note{{color:#777;font-size:13px}}</style></head><body>
<h2>Система учёта заявок — эмуляция</h2>
<p class="note">Так заявки видит help desk заказчика. Стадии идут по времени; обновление каждые 15 с.</p>
<table><tr><th>№ help desk</th><th>№ заявки</th><th>Заявка</th><th>Объект</th><th>Приоритет</th><th>Статус</th>
<th>Исполнитель</th><th>Обновлено (UTC)</th><th></th></tr>{lines}</table></body></html>"""
        data = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    init()
    port = int(os.environ.get("PORT", "8080"))
    print(f"mock help desk on :{port}, stages {STAGE_MINUTES} min", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
