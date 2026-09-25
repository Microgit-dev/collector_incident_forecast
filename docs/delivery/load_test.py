"""
Нагрузочная проверка требования ТЗ §11: не менее 20 одновременных пользователей без деградации.

20 виртуальных пользователей (демо-учётки разных ролей) в течение DURATION секунд без пауз
открывают типичные экраны: главный экран, очередь инцидентов, карточку инцидента, схему, журнал
прогнозов, карточку прогноза, аналитику. Печатает задержки по эндпоинтам (медиана, 95-й процентиль),
пропускную способность и ошибки.

    uv run --no-project --with httpx python docs/delivery/load_test.py https://localhost [пользователей] [секунд] [пауза, с]
"""

from __future__ import annotations

import asyncio
import random
import statistics
import sys
import time
from collections import defaultdict

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://localhost").rstrip("/") + "/api/v1"
USERS = int(sys.argv[2]) if len(sys.argv) > 2 else 20
DURATION = int(sys.argv[3]) if len(sys.argv) > 3 else 60
# пауза между действиями, с: 0 — стресс без пауз, иначе случайно от 1 до THINK (как живой диспетчер)
THINK = float(sys.argv[4]) if len(sys.argv) > 4 else 0
PASSWORD = "Passw0rd!"
LOGINS = [
    "ods.ivanov",
    "ods.kozlova",
    "disp.petrov",
    "disp.nikolaev",
    "disp.fedorova",
    "head.sidorova",
    "analyst.kuznetsov",
    "observer.orlova",
]
SCREENS = [
    ("главный экран", "/analytics/live/?minutes=10", 4),
    ("очередь инцидентов", "/incidents/items/?status__in=new,acknowledged,in_progress", 3),
    ("карточка инцидента", "/incidents/items/{incident}/", 3),
    ("схема объектов", "/analytics/scheme/", 1),
    ("журнал прогнозов", "/forecasting/predictions/?is_backtest=false", 2),
    ("карточка прогноза", "/forecasting/predictions/{prediction}/", 2),
    ("эффективность", "/analytics/efficiency/", 1),
]


async def login(client: httpx.AsyncClient, username: str) -> str:
    r = await client.post(f"{BASE}/auth/token/", json={"username": username, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["access"]


async def user(client, token, ids, stats, errors, stop_at):
    headers = {"Authorization": f"Bearer {token}"}
    names, paths, weights = zip(*SCREENS, strict=True)
    while time.monotonic() < stop_at:
        i = random.choices(range(len(SCREENS)), weights)[0]
        path = paths[i].format(
            incident=random.choice(ids["incident"]), prediction=random.choice(ids["prediction"])
        )
        t0 = time.perf_counter()
        try:
            r = await client.get(BASE + path, headers=headers)
            ok = r.status_code < 400 or r.status_code == 404  # чужая зона даёт 404 — это не ошибка сервиса
        except httpx.HTTPError:
            ok = False
        stats[names[i]].append(time.perf_counter() - t0)
        if not ok:
            errors[names[i]] += 1
        if THINK:
            await asyncio.sleep(random.uniform(1, THINK))


async def main():
    async with httpx.AsyncClient(verify=False, timeout=60) as client:
        tokens = [await login(client, LOGINS[i % len(LOGINS)]) for i in range(USERS)]
        head = {"Authorization": f"Bearer {tokens[0]}"}
        incidents = (await client.get(f"{BASE}/incidents/items/?page_size=50", headers=head)).json()[
            "results"
        ]
        predictions = (await client.get(f"{BASE}/forecasting/predictions/?page_size=50", headers=head)).json()
        ids = {
            "incident": [i["id"] for i in incidents],
            "prediction": [p["id"] for p in predictions["results"]],
        }
        stats, errors = defaultdict(list), defaultdict(int)
        start = time.monotonic()
        await asyncio.gather(*(user(client, t, ids, stats, errors, start + DURATION) for t in tokens))
        elapsed = time.monotonic() - start
    total = sum(len(v) for v in stats.values())
    mode = f"паузы 1–{THINK:g} с" if THINK else "без пауз (стресс)"
    print(
        f"пользователей {USERS}, {mode}, {elapsed:.0f} с, запросов {total}, {total / elapsed:.1f} в секунду"
    )
    print(f"{'экран':<22}{'запросов':>9}{'медиана, мс':>13}{'95 %, мс':>10}{'ошибок':>8}")
    for name, values in sorted(stats.items()):
        values.sort()
        p95 = values[min(len(values) - 1, int(0.95 * len(values)))]
        print(
            f"{name:<22}{len(values):>9}{statistics.median(values) * 1000:>13.0f}{p95 * 1000:>10.0f}{errors[name]:>8}"
        )
    all_values = sorted(v for vs in stats.values() for v in vs)
    print(
        f"{'все':<22}{total:>9}{statistics.median(all_values) * 1000:>13.0f}"
        f"{all_values[int(0.95 * len(all_values))] * 1000:>10.0f}{sum(errors.values()):>8}"
    )


if __name__ == "__main__":
    import warnings

    warnings.filterwarnings("ignore")
    asyncio.run(main())
