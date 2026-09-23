"""
Клиенты внешних систем. Все взаимодействия с системами заказчика — только чтение (ТЗ §13),
а сами системы в стенде эмулируются (mock-helpdesk в docker compose).
"""

from __future__ import annotations

from datetime import date

import httpx
from django.conf import settings

MOSCOW = {"latitude": 55.75, "longitude": 37.62}
HOURLY = "temperature_2m,relative_humidity_2m,precipitation,snowfall,surface_pressure"


class WeatherClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self.base_url = base_url or settings.INTEGRATIONS["WEATHER_URL"]
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
    """Система учёта заявок заказчика (help desk на Django): получение статусов заявок."""

    def __init__(self, base_url: str | None = None, timeout: float = 10.0):
        self.base_url = (base_url or settings.INTEGRATIONS["HELPDESK_URL"]).rstrip("/")
        self.timeout = timeout

    def submit(self, payload: dict) -> dict:
        response = httpx.post(f"{self.base_url}/api/tickets/", json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def statuses(self, external_ids: list[str]) -> dict[str, str]:
        response = httpx.get(
            f"{self.base_url}/api/tickets/statuses/",
            params={"ids": ",".join(external_ids)},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
