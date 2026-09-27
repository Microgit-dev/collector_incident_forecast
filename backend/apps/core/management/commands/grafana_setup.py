"""
Права папок Grafana после запуска (провижининг файлами права папок не задаёт).

«Система» — только администраторам Grafana (роль Admin приходит с правом
accounts.view_system_monitoring), «Аналитика» — всем, кто вошёл (Viewer — аналитик).
Домашняя панель организации — бизнес-дашборд. Идемпотентна: запускается сервисом grafana-init.
"""

import os
import time

import httpx
from django.core.management.base import BaseCommand, CommandError

SYSTEM_FOLDER = "system"
ANALYTICS_FOLDER = "analytics"
HOME_DASHBOARD = "collector-business"


class Command(BaseCommand):
    help = "Выставляет права папок Grafana и домашнюю панель"

    def add_arguments(self, parser):
        parser.add_argument("--url", default=os.environ.get("GRAFANA_URL", "http://grafana:3000/grafana"))
        parser.add_argument("--wait", type=int, default=180, help="сколько секунд ждать запуска Grafana")

    def handle(self, *args, url, wait, **options):
        auth = (os.environ.get("GRAFANA_ADMIN_USER", "admin"), os.environ.get("GRAFANA_ADMIN_PASSWORD", ""))
        client = httpx.Client(base_url=url.rstrip("/"), auth=auth, timeout=10)
        self._wait(client, wait)
        for uid in (SYSTEM_FOLDER, ANALYTICS_FOLDER):
            self._wait_folder(client, uid, wait)
        # Пустой список — папку видят только администраторы организации
        self._post(client, f"/api/folders/{SYSTEM_FOLDER}/permissions", {"items": []})
        self._post(
            client,
            f"/api/folders/{ANALYTICS_FOLDER}/permissions",
            {"items": [{"role": "Viewer", "permission": 1}, {"role": "Editor", "permission": 1}]},
        )
        response = client.put("/api/org/preferences", json={"homeDashboardUID": HOME_DASHBOARD})
        if response.status_code >= 400:
            self.stdout.write(f"домашняя панель не выставлена: {response.status_code} {response.text[:200]}")
        self.stdout.write(self.style.SUCCESS("grafana: права папок выставлены"))

    def _wait(self, client: httpx.Client, wait: int) -> None:
        deadline = time.monotonic() + wait
        while True:
            try:
                if client.get("/api/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise CommandError("Grafana не ответила")
            time.sleep(3)

    def _wait_folder(self, client: httpx.Client, uid: str, wait: int) -> None:
        # папки появляются после провижининга, чуть позже готовности API
        deadline = time.monotonic() + wait
        while client.get(f"/api/folders/{uid}").status_code != 200:
            if time.monotonic() > deadline:
                raise CommandError(f"В Grafana нет папки {uid}: проверьте provisioning/dashboards")
            time.sleep(3)

    def _post(self, client: httpx.Client, path: str, body: dict) -> None:
        response = client.post(path, json=body)
        if response.status_code >= 400:
            raise CommandError(f"{path}: {response.status_code} {response.text[:200]}")
