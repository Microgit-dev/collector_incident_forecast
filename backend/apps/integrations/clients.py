"""
Клиенты внешних систем. С системами заказчика обмен только на чтение (ТЗ §13), кроме передачи
утверждённой заявки в систему учёта заявок. Адреса, авторизация и соответствие статусов — в .env
(settings.INTEGRATIONS); на стенде те же клиенты ходят в эмуляторы mock-helpdesk и mock-vms.
"""

from __future__ import annotations

from datetime import date

import httpx
from django.conf import settings

MOSCOW = {"latitude": 55.75, "longitude": 37.62}
HOURLY = "temperature_2m,relative_humidity_2m,precipitation,snowfall,surface_pressure"


def conf(key: str):
    return settings.INTEGRATIONS[key]


def auth_headers(token: str, scheme: str = "Bearer") -> dict[str, str]:
    """Заголовок авторизации: Bearer/Token — токен; Basic — «логин:пароль» в токене."""
    if not token:
        return {}
    if scheme.lower() == "basic":
        import base64

        return {"Authorization": "Basic " + base64.b64encode(token.encode()).decode()}
    return {"Authorization": f"{scheme} {token}"}


def verify(ca_cert: str) -> str | bool:
    """Проверка сертификата: корневой сертификат ЦС заказчика или системное хранилище."""
    return ca_cert or True


class WeatherClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self.base_url = base_url or conf("WEATHER_URL")
        self.timeout = timeout

    def hourly(self, start: date, end: date) -> dict:
        params = {
            **MOSCOW,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": HOURLY,
            "timezone": "Europe/Moscow",
        }
        response = httpx.get(self.base_url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()


class HelpdeskClient:
    """
    Система учёта заявок заказчика: передача заявки и статусы переданных заявок.

    Контракт: POST {submit_path} с заявкой → {"id", "status", "status_label", "assignee", "history",
    "report"}; GET {status_path}?ids=a,b → {"a": {...}, "b": {...}}. Статусы заказчика переводятся
    в наши по HELPDESK_STATUS_MAP (workorders.services.external_status).
    """

    def __init__(self, base_url: str | None = None, timeout: float = 10.0):
        self.base_url = (base_url or conf("HELPDESK_URL")).rstrip("/")
        self.timeout = timeout
        self.headers = auth_headers(conf("HELPDESK_TOKEN"), conf("HELPDESK_AUTH_SCHEME"))
        self.verify = verify(conf("HELPDESK_CA_CERT"))

    def _url(self, key: str) -> str:
        return self.base_url + "/" + conf(key).lstrip("/")

    def submit(self, payload: dict) -> dict:
        response = httpx.post(
            self._url("HELPDESK_SUBMIT_PATH"),
            json=payload,
            headers=self.headers,
            timeout=self.timeout,
            verify=self.verify,
        )
        response.raise_for_status()
        return response.json()

    def statuses(self, external_ids: list[str]) -> dict[str, dict]:
        response = httpx.get(
            self._url("HELPDESK_STATUS_PATH"),
            params={"ids": ",".join(external_ids)},
            headers=self.headers,
            timeout=self.timeout,
            verify=self.verify,
        )
        response.raise_for_status()
        return response.json()

    def ping(self) -> dict:
        """Проверка связи: запрос статусов пустого списка (только чтение)."""
        return {"statuses": len(self.statuses([]))}


class RegistryClient:
    """
    Учётная система оборудования заказчика (только чтение): GET {REGISTRY_URL} → список единиц
    [{"inventory_number", "kind", "name", "object", ...}] или {"results": [...], "next": url}.
    Поля — как в файле реестра (apps/assets/registry_sync.py).
    """

    def __init__(self, url: str | None = None, timeout: float = 60.0):
        self.url = url or conf("REGISTRY_URL")
        self.timeout = timeout
        self.headers = auth_headers(conf("REGISTRY_TOKEN"))
        self.verify = verify(conf("REGISTRY_CA_CERT"))

    def rows(self) -> list[dict]:
        if not self.url:
            raise ValueError("REGISTRY_URL не задан")
        rows: list[dict] = []
        url: str | None = self.url
        while url:
            response = httpx.get(url, headers=self.headers, timeout=self.timeout, verify=self.verify)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                return rows + data
            rows.extend(data.get("results", []))
            url = data.get("next")
        return rows


class VideoClient:
    """
    Система видеонаблюдения заказчика (только чтение): кадр камеры на момент времени.
    GET {VMS_URL}{VMS_SNAPSHOT_PATH}?at=ISO → изображение (JPEG/PNG; эмулятор отдаёт SVG).
    """

    def __init__(self, timeout: float = 10.0):
        self.base_url = conf("VMS_URL").rstrip("/")
        self.timeout = timeout
        self.headers = auth_headers(conf("VMS_TOKEN"))
        self.verify = verify(conf("VMS_CA_CERT"))

    def snapshot(self, camera_id: str, at: str | None = None) -> tuple[bytes, str]:
        path = conf("VMS_SNAPSHOT_PATH").format(id=camera_id)
        response = httpx.get(
            self.base_url + path,
            params={"at": at} if at else None,
            headers=self.headers,
            timeout=self.timeout,
            verify=self.verify,
        )
        response.raise_for_status()
        return response.content, response.headers.get("content-type", "application/octet-stream")

    def ping(self) -> dict:
        response = httpx.get(
            self.base_url + "/health", headers=self.headers, timeout=self.timeout, verify=self.verify
        )
        response.raise_for_status()
        return {"status": response.status_code}
