"""
Перечень библиотек и компонентов (ТЗ §14) → docs/delivery/libraries.md.

Версии и лицензии берутся из установленных пакетов, а не пишутся руками, поэтому перечень
совпадает с тем, что реально собрано. Запуск из корня репозитория:

    cd backend && uv run python ../docs/delivery/gen_libraries.py
"""

from __future__ import annotations

import json
import re
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "delivery" / "libraries.md"

PURPOSE = {
    "django": "веб-фреймворк, ORM, админка, RBAC",
    "djangorestframework": "REST API",
    "djangorestframework-simplejwt": "JWT-аутентификация",
    "drf-spectacular": "OpenAPI / Swagger",
    "django-filter": "фильтры API",
    "django-cors-headers": "CORS",
    "django-environ": "настройки из окружения",
    "whitenoise": "раздача статики",
    "psycopg": "драйвер PostgreSQL",
    "redis": "клиент Redis",
    "django-treebeard": "дерево объектов (materialized path)",
    "django-auditlog": "история изменений моделей",
    "celery": "фоновые и периодические задачи",
    "django-celery-beat": "расписание задач в БД",
    "channels": "WebSocket-уведомления",
    "channels-redis": "слой каналов на Redis",
    "uvicorn": "ASGI-сервер",
    "confluent-kafka": "клиент Kafka",
    "django-prometheus": "метрики Prometheus",
    "polars": "обработка данных, признаки",
    "pyarrow": "Parquet-архив",
    "numpy": "численные расчёты",
    "scikit-learn": "метрики качества моделей",
    "lightgbm": "градиентный бустинг — модели прогноза",
    "joblib": "сериализация",
    "httpx": "HTTP-клиент интеграций",
    "openpyxl": "XLSX: импорт журналов и отчёты",
    "fpdf2": "PDF-отчёты",
    "django-auth-ldap": "вход через LDAP / AD",
    "python-ldap": "клиент LDAP",
    "ruff": "линтер и форматирование (разработка)",
    "pytest": "тесты (разработка)",
    "pytest-django": "тесты Django (разработка)",
    "factory-boy": "тестовые данные (разработка)",
}
NPM_PURPOSE = {
    "react": "интерфейс",
    "react-dom": "интерфейс",
    "react-router-dom": "маршрутизация SPA",
    "@mantine/core": "компоненты интерфейса",
    "@mantine/charts": "графики",
    "@mantine/dates": "выбор дат",
    "@mantine/hooks": "хуки интерфейса",
    "@mantine/notifications": "уведомления",
    "@tabler/icons-react": "иконки",
    "@tanstack/react-query": "загрузка и кеш данных API",
    "dayjs": "даты и время",
    "recharts": "графики (основа @mantine/charts)",
    "typescript": "типизация (сборка)",
    "vite": "сборка (разработка)",
    "@vitejs/plugin-react": "сборка (разработка)",
    "oxlint": "линтер (разработка)",
    "postcss": "стили (сборка)",
    "postcss-preset-mantine": "стили (сборка)",
    "postcss-simple-vars": "стили (сборка)",
}


LOCK = {
    pkg["name"].lower(): pkg["version"]
    for pkg in tomllib.loads((ROOT / "backend" / "uv.lock").read_text(encoding="utf-8")).get("package", [])
    if "version" in pkg
}
KNOWN_LICENSE = {"django-auth-ldap": "BSD-2-Clause", "python-ldap": "Python (PSF-style)"}


def _name(requirement: str) -> str:
    return re.split(r"[\[<>=~!; ]", requirement, maxsplit=1)[0].strip()


def _license(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [
        c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")
    ]
    if classifiers:
        return ", ".join(dict.fromkeys(classifiers))
    value = (meta.get("License") or "").strip()
    return value.splitlines()[0][:40] if value else "—"


def python_rows() -> list[tuple[str, str, str, str]]:
    project = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    names = [_name(r) for r in project["project"]["dependencies"]]
    for group in project.get("dependency-groups", {}).values():
        names += [_name(r) for r in group if isinstance(r, str)]
    rows = []
    for name in dict.fromkeys(names):
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            # пакет из группы, не установленной локально (python-ldap не собирается на Windows) — версия из lock
            rows.append(
                (
                    name,
                    LOCK.get(name.lower(), "?"),
                    KNOWN_LICENSE.get(name.lower(), "—"),
                    PURPOSE.get(name.lower(), ""),
                )
            )
            continue
        rows.append((name, dist.version, _license(dist), PURPOSE.get(name.lower(), "")))
    return rows


def npm_rows() -> list[tuple[str, str, str, str]]:
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    rows = []
    for section in ("dependencies", "devDependencies"):
        for name in package.get(section, {}):
            path = ROOT / "frontend" / "node_modules" / name / "package.json"
            if path.exists():
                info = json.loads(path.read_text(encoding="utf-8"))
                version, license_ = info.get("version", "?"), info.get("license", "—")
            else:
                version, license_ = package[section][name], "—"
            if isinstance(license_, dict):
                license_ = license_.get("type", "—")
            if name.startswith("@types/"):
                continue
            rows.append((name, version, license_, NPM_PURPOSE.get(name, "")))
    return rows


def image_rows() -> list[tuple[str, str]]:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    images = sorted(
        {m.strip() for m in re.findall(r"image:\s*(\S+)", compose) if "collector-forecast/" not in m}
    )
    return [
        (image.rsplit(":", 1)[0], image.rsplit(":", 1)[1] if ":" in image else "latest") for image in images
    ]


def table(header: tuple[str, ...], rows) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


IMAGE_PURPOSE = {
    "timescale/timescaledb": "PostgreSQL 16 + TimescaleDB — основное хранилище",
    "redis": "брокер Celery, кеш, слой каналов WebSocket",
    "apache/kafka": "поток событий СМВУ (KRaft, без ZooKeeper)",
    "osixia/openldap": "тестовый каталог LDAP (эмуляция AD заказчика)",
    "prom/prometheus": "сбор метрик",
    "grafana/grafana": "дашборды мониторинга и бизнес-показателей",
    "prometheuscommunity/postgres-exporter": "метрики PostgreSQL",
    "oliver006/redis_exporter": "метрики Redis",
    "danihodovic/celery-exporter": "метрики Celery",
    "provectuslabs/kafka-ui": "просмотр топиков Kafka",
    "prodrigestivill/postgres-backup-local": "ежедневные резервные копии pg_dump",
}


def main() -> None:
    parts = [
        "# Перечень библиотек и компонентов",
        "",
        "Сформирован автоматически из установленных пакетов (`docs/delivery/gen_libraries.py`). Полный граф "
        "зависимостей с точными версиями зафиксирован в `backend/uv.lock` и `frontend/package-lock.json`.",
        "",
        "## Backend (Python 3.12)",
        "",
        table(("Библиотека", "Версия", "Лицензия", "Назначение"), python_rows()),
        "",
        "## Frontend (TypeScript)",
        "",
        table(("Библиотека", "Версия", "Лицензия", "Назначение"), npm_rows()),
        "",
        "## Компоненты инфраструктуры (образы Docker)",
        "",
        table(
            ("Образ", "Тег", "Назначение"),
            [(name, tag, IMAGE_PURPOSE.get(name, "")) for name, tag in image_rows()],
        ),
        "",
        "Собственные образы: `collector-forecast/backend` (Django, Celery, консьюмер Kafka — одна сборка), "
        "`collector-forecast/web` (Caddy с собранным интерфейсом, TLS), `collector-forecast/mock-helpdesk` "
        "(эмулятор системы заявок, только стандартная библиотека Python). Внешние платные сервисы и облачные "
        "API не используются; единственный внешний источник — открытый API Open-Meteo (без ключа), без него "
        "система работает, теряя только погодные признаки.",
        "",
    ]
    OUT.write_text("\n".join(parts), encoding="utf-8", newline="\n")
    print(f"written {OUT}")


if __name__ == "__main__":
    main()
