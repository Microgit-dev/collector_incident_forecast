"""
Калибровка индекса правил-индикаторов (пожар, НСД) в вероятность (чистые функции).

Индекс правил — не вероятность: он складывает подтверждения. Вероятность получается из истории:
индекс считается по архиву теми же правилами, для каждого момента известен исход — «угроза
проявилась» (тревоги того же рода на объекте через 1–24 ч). Доля проявившихся среди случаев
с похожим индексом и есть вероятность.

Как считаем:
- индекс делится на фиксированные интервалы (EDGES) — у каждого интервала n случаев и k исходов;
- доля сглаживается к общей частоте (ALPHA псевдослучаев): редкий интервал не даёт 0 % или 100 %;
- доли выравниваются по возрастанию (PAVA, взвешенно по n): больший индекс не может давать
  меньшую вероятность.
Результат — ступенчатая функция, которую можно объяснить словами: «из 412 похожих случаев угроза
проявилась в 38 %».
"""

from __future__ import annotations

from collections.abc import Iterable

EDGES = (0.15, 0.3, 0.4, 0.5, 0.6, 0.75, 0.9, 1.0)
ALPHA = 10.0


def _bin(score: float, edges: tuple[float, ...] = EDGES) -> int | None:
    if score < edges[0]:
        return None
    for i in range(len(edges) - 1):
        if score < edges[i + 1]:
            return i
    return len(edges) - 2  # индекс 0,99 и выше — в последний интервал


def _pava(values: list[float], weights: list[float]) -> list[float]:
    """Взвешенная изотоническая регрессия (pool adjacent violators): неубывающая последовательность."""
    blocks: list[list[float]] = []  # [значение, вес, число элементов]
    for v, w in zip(values, weights, strict=True):
        blocks.append([v, w, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            v2, w2, c2 = blocks.pop()
            v1, w1, c1 = blocks.pop()
            weight = w1 + w2
            blocks.append([(v1 * w1 + v2 * w2) / weight if weight else (v1 + v2) / 2, weight, c1 + c2])
    result: list[float] = []
    for v, _, count in blocks:
        result.extend([v] * count)
    return result


def fit(
    samples: Iterable[tuple[float, bool]], edges: tuple[float, ...] = EDGES, alpha: float = ALPHA
) -> dict:
    """
    samples — пары (индекс, угроза проявилась). Возвращает калибровку:
    {"edges", "base_rate", "bins": [{"lo", "hi", "n", "k", "p"}], "n", "k"}.
    """
    n = [0] * (len(edges) - 1)
    k = [0] * (len(edges) - 1)
    for score, outcome in samples:
        i = _bin(score, edges)
        if i is None:
            continue
        n[i] += 1
        k[i] += bool(outcome)
    total, positives = sum(n), sum(k)
    base = positives / total if total else 0.0
    raw = [(k[i] + alpha * base) / (n[i] + alpha) for i in range(len(n))]
    smooth = _pava(raw, [n[i] + alpha for i in range(len(n))])
    bins = [
        {"lo": edges[i], "hi": edges[i + 1], "n": n[i], "k": k[i], "p": round(smooth[i], 4)}
        for i in range(len(n))
    ]
    return {"edges": list(edges), "base_rate": round(base, 4), "bins": bins, "n": total, "k": positives}


def probability(calibration: dict, score: float) -> float | None:
    """Вероятность проявления угрозы для индекса; None — индекс ниже калиброванного диапазона."""
    i = _bin(score, tuple(calibration["edges"]))
    return None if i is None else calibration["bins"][i]["p"]


def evidence(calibration: dict, score: float) -> dict | None:
    """Интервал калибровки, из которого взята вероятность: для пояснения в карточке."""
    i = _bin(score, tuple(calibration["edges"]))
    return None if i is None else calibration["bins"][i]


def brier(pairs: Iterable[tuple[float, bool]]) -> float | None:
    pairs = list(pairs)
    if not pairs:
        return None
    return round(sum((p - float(y)) ** 2 for p, y in pairs) / len(pairs), 4)


def reliability(calibration: dict, samples: Iterable[tuple[float, bool]]) -> list[dict]:
    """Проверка на отложенных данных: по интервалам — предсказанная вероятность и фактическая доля."""
    rows = [{**b, "n": 0, "k": 0} for b in calibration["bins"]]
    for score, outcome in samples:
        i = _bin(score, tuple(calibration["edges"]))
        if i is not None:
            rows[i]["n"] += 1
            rows[i]["k"] += bool(outcome)
    return [
        {
            "lo": r["lo"],
            "hi": r["hi"],
            "p": r["p"],
            "n": r["n"],
            "observed": round(r["k"] / r["n"], 4) if r["n"] else None,
        }
        for r in rows
    ]
