"""
Контракты прогнозных моделей. Каждая задача (отказ датчика, газ, подтопление, пожар, НСД)
реализует Forecaster; ядро не знает, LightGBM это, статистика или правила.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Factor:
    feature: str
    title: str  # человекочитаемое объяснение для карточки прогноза
    value: float | str | None
    contribution: float  # вклад в вероятность (SHAP / вес правила)


@dataclass(frozen=True, slots=True)
class ForecastResult:
    node_id: int
    channel_id: int | None
    probability: float
    horizon_hours: int
    factors: list[Factor] = field(default_factory=list)
    summary: str = ""


class Forecaster(Protocol):
    task: str
    horizon_hours: int

    def predict(self, as_of: datetime, node_ids: list[int] | None = None) -> list[ForecastResult]:
        """Прогноз на момент as_of по объектам/каналам (inference ≤ 300 с на объект — ТЗ §11)."""
        ...
