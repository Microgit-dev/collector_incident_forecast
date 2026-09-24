"""
Операционный приоритет карточки 0–100: что диспетчеру открыть первым.

    приоритет = 100 × тяжесть × контур × критичность объекта × уверенность данных × срочность × вероятность

тяжесть           уровень риска: критический 1,0 … низкий 0,25;
контур            физическая угроза важнее технической (0,7): пожар раньше, чем сбой датчика;
критичность       объект 1–5 из справочника → 0,7…1,1;
уверенность       средний Data Health Score каналов эпизода → 0,5…1,0; для физических угроз
                  подтверждение несколькими каналами повышает уверенность, а вес гипотезы
                  «реальная угроза» против «ложного срабатывания» — умножает на 0,6…1,0;
срочность         доля истёкшего времени на реакцию → 1,0…1,5, эскалация +0,2 за уровень;
вероятность       для прогноза — вероятность, для факта — 1.
Итог ограничен 100. Составляющие хранятся в карточке, чтобы приоритет можно было объяснить.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

SEVERITY = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}
CONTOUR = {"physical": 1.0, "technical": 0.7}


@dataclass(frozen=True, slots=True)
class PriorityInput:
    severity: str
    contour: str
    criticality: int
    health: float | None  # средний балл 0–100, None — нет данных
    channels: int
    opened_at: datetime
    ack_deadline: datetime | None
    escalation_level: int
    acknowledged: bool
    probability: float | None
    now: datetime
    real_threat: float | None = None  # вес гипотезы «угроза реальна» (физический контур)


def priority(x: PriorityInput) -> tuple[float, dict]:
    severity = SEVERITY.get(x.severity, 0.5)
    contour = CONTOUR.get(x.contour, 0.7)
    criticality = 0.6 + 0.1 * max(1, min(x.criticality, 5))
    confidence = 0.5 + 0.5 * (x.health / 100) if x.health is not None else 0.85
    if x.contour == "physical" and x.channels >= 2:
        confidence = min(1.0, confidence + 0.1 * (x.channels - 1))
    if x.contour == "physical" and x.real_threat is not None:
        confidence *= 0.6 + 0.4 * x.real_threat
    urgency = 1.0
    if not x.acknowledged and x.ack_deadline and x.ack_deadline > x.opened_at:
        window = (x.ack_deadline - x.opened_at).total_seconds()
        elapsed = (x.now - x.opened_at).total_seconds()
        urgency += 0.5 * max(0.0, min(elapsed / window, 1.0))
    urgency += 0.2 * x.escalation_level
    probability = x.probability if x.probability is not None else 1.0
    score = min(100.0, 100 * severity * contour * criticality * confidence * urgency * probability)
    factors = {
        "severity": round(severity, 2),
        "contour": contour,
        "criticality": round(criticality, 2),
        "confidence": round(confidence, 2),
        "urgency": round(urgency, 2),
        "probability": round(probability, 3),
    }
    return round(score, 1), factors
