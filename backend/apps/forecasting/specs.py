"""
Задачи прогноза по каналу. Каждая задача — это набор датчиков, событие-метка, условие «канал
в норме сейчас» (прогнозируется начало события, а не его продолжение), признаки и правило-ориентир
для сравнения. Конвейер обучения и прогноза общий (channel_model.py).

    sensor_failure — отказ датчика: канал сообщит о неисправности;
    gas            — превышение 1 % метана: суточный максимум по корректным значениям ≥ 1 %
                     (служебные коды и артефакты в концентрацию не входят — это делает нормализация);
    flood          — подтопление: тревога насоса АНС («Затоплен», «Работают все насосы»)
                     или датчика затопления.
Пожар и проникновение — правила-индикаторы (scenarios.py): их тревоги в журналах в основном
ложные, и модель на них училась бы предсказывать ложные срабатывания, а не угрозу.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import polars as pl

from .domain import features as F


@dataclass(frozen=True)
class TaskSpec:
    task: str
    title: str
    event_title: str
    incident_type: str
    features: list[str]
    event: Callable[[], pl.Expr]
    healthy: Callable[[], pl.Expr]
    sensor_types: tuple[str, ...] | None = None
    event_ts: str | None = None
    baseline_rule: str = ""
    baseline: Callable[[pl.DataFrame], object] = lambda frame: None
    neg_rate: float = 0.05
    params: dict = field(default_factory=dict)
    # Исход прогноза по факту: условия на суточную витрину (d) и оперативный контур (r)
    resolve_daily: str = "d.first_fault_ts > p.issued_at AND d.first_fault_ts <= p.valid_until"
    resolve_reading: str = "r.state = 'fault'"
    uses_feedback: bool = False
    # То же событие и «канал в норме» на суточной витрине (SQL) — для фактической полноты журнала
    event_sql: str = "d.first_fault_ts IS NOT NULL"
    healthy_sql: str = "d.last_state <> 'fault'"
    # Уровни риска по точности на валидации; для редких событий ориентиры ниже — иначе уровней не будет
    level_precision: dict = field(default_factory=lambda: {"critical": 0.7, "high": 0.4, "medium": 0.15})


SENSOR_FAILURE = TaskSpec(
    task="sensor_failure",
    title="Отказ датчика",
    event_title="неисправность канала",
    incident_type="sensor_failure",
    features=F.FEATURES,
    event=F.fault_event,
    healthy=F.not_faulty,
    event_ts="first_fault_ts",
    baseline_rule="неисправность за последние 7 суток",
    baseline=lambda frame: (frame["faults_7"] > 0).to_numpy(),
    uses_feedback=True,
)

GAS = TaskSpec(
    task="gas",
    title="Превышение 1 % метана",
    event_title="превышение 1 % метана",
    incident_type="gas",
    features=[*F.FEATURES, *F.EXTRA_FEATURES],
    event=lambda: pl.col("numeric_max") >= F.EXCEED_LEVEL,
    healthy=lambda: (pl.col("numeric_max").fill_null(0) < F.EXCEED_LEVEL) & (pl.col("last_state") != "alarm"),
    sensor_types=("Газовый датчик",),
    baseline_rule="за последние 7 суток был уровень ≥ 0,5 %",
    baseline=lambda frame: (frame["num_max_7"].fill_null(0) >= 0.5).to_numpy(),
    # газовых каналов около 460 — выборка помещается целиком, без прореживания
    neg_rate=1.0,
    params={"min_data_in_leaf": 100, "learning_rate": 0.02},
    level_precision={"critical": 0.3, "high": 0.12, "medium": 0.05},
    resolve_daily=f"d.numeric_max >= {F.EXCEED_LEVEL} AND d.day > (p.issued_at AT TIME ZONE 'Europe/Moscow')::date",
    resolve_reading=f"r.numeric >= {F.EXCEED_LEVEL} AND r.quality IN ('ok', 'drift')",
    event_sql=f"d.numeric_max >= {F.EXCEED_LEVEL}",
    healthy_sql=f"coalesce(d.numeric_max, 0) < {F.EXCEED_LEVEL} AND d.last_state <> 'alarm'",
)

FLOOD = TaskSpec(
    task="flood",
    title="Подтопление",
    event_title="тревога затопления (насосы АНС, датчики затопления)",
    incident_type="flood",
    features=[*F.FEATURES, *F.EXTRA_FEATURES],
    event=lambda: pl.col("alarms") > 0,
    healthy=lambda: pl.col("last_state") != "alarm",
    sensor_types=("Состояние насоса", "Датчик затопления"),
    baseline_rule="тревога за последние 7 суток",
    baseline=lambda frame: (frame["alarms_7"] > 0).to_numpy(),
    neg_rate=0.2,
    params={"min_data_in_leaf": 200},
    resolve_daily="d.alarms > 0 AND d.day > (p.issued_at AT TIME ZONE 'Europe/Moscow')::date",
    resolve_reading="r.state = 'alarm'",
    event_sql="d.alarms > 0",
    healthy_sql="d.last_state <> 'alarm'",
)

SPECS: dict[str, TaskSpec] = {s.task: s for s in (SENSOR_FAILURE, GAS, FLOOD)}


def get(task: str) -> TaskSpec:
    if task not in SPECS:
        raise ValueError(f"Задача {task} решается правилами, обучение не требуется")
    return SPECS[task]
