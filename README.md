# Прогноз инцидентов инженерных коллекторов

Сервис прогнозирования технических отказов датчиков и раннего выявления риска инцидентов
(пожар, загазованность, подтопление, несанкционированный доступ) с ролевой моделью
и вертикалью управления: от сигнала датчика до решения диспетчера и заявки бригаде.

Задача — «8. ДЖКХ» (АО «Москоллектор»). Дорожная карта и статусы — [ROADMAP.md](ROADMAP.md).

## Быстрый старт

Нужен Docker с Compose v2. Всё разворачивается локально, внешние сервисы не требуются.

```bash
cp .env.example .env              # при необходимости поменяйте пароли и порты
docker compose up -d --build      # первая сборка ~5–10 минут
```

| Что | Адрес |
|---|---|
| Интерфейс диспетчера | https://localhost (сертификат локального CA Caddy — подтвердите исключение) |
| API (OpenAPI/Swagger) | https://localhost/api/docs/ |
| Администрирование | https://localhost/admin/ |
| Мониторинг (Grafana) | https://localhost/grafana/ |
| Kafka UI | http://localhost:8081 |

Учётные записи по умолчанию:
- суперпользователь `admin` / `admin12345` (из `.env`);
- LDAP-учётки по ролям, пароль `Passw0rd!`: `ods.ivanov`, `disp.petrov`, `head.sidorova`,
  `analyst.kuznetsov`, `brigade.smirnov`, `observer.orlova`, `admin.volkov`.

Сырые данные заказчика кладутся в `data/` (в git не хранятся), см. [data/README.md](data/README.md).

### Данные

Справочники (дерево объектов, 11 485 каналов, пикеты) загружаются автоматически при первом запуске.
Историю журналов загружает отдельная команда — примерно минута на год данных:

```bash
docker compose run --rm backend python manage.py import_history            # все годы, кроме 2021
docker compose run --rm backend python manage.py import_history --years 2025 2026 --raw-days 30
```

Результат: Parquet-архив в `artifacts/archive/`, суточная витрина за всю историю, сырые показания
за оперативное окно и отчёт о качестве загрузки (интерфейс → «Качество данных»).
Решение по контурам хранения описано в [docs/adr/0001-storage-contours.md](docs/adr/0001-storage-contours.md).

Демо-поток СМВУ: реальный журнал проигрывается в Kafka с ускорением.

```bash
docker compose --profile demo up -d replay
```

## Архитектура

Модульный монолит на Django + DRF, внутри каждого модуля — слои `models / services / selectors / domain / api`.
Подробно: [docs/architecture.md](docs/architecture.md).

```
Источники (адаптеры)        Ядро                                       Клиенты
CSV/XLSX, СМВУ→Kafka  ──▶  ingestion → normalization → telemetry  ──▶  React SPA (WebSocket)
mock help desk, погода      forecasting → incidents → workorders        Django admin, Grafana
LDAP                        accounts/topology (RBAC + зоны) · audit      REST API
```

| Компонент | Технология |
|---|---|
| Backend | Python 3.12, Django 5.2, DRF, Channels, Celery, uv |
| Хранилище | PostgreSQL 16 + TimescaleDB (hypertable, сжатие, continuous aggregates), Redis |
| Поток | Apache Kafka 3.9 (KRaft) |
| ML | LightGBM, scikit-learn, Polars/Parquet |
| Frontend | React 19, TypeScript, Vite, Mantine, TanStack Query |
| Инфраструктура | Docker Compose, Caddy (TLS), Prometheus, Grafana, OpenLDAP, pg_dump-бэкапы |

## Разработка

```bash
cd backend
uv sync                          # зависимости + dev-инструменты
uv run pytest                    # тесты (SQLite, без внешних сервисов)
uv run ruff check . && uv run ruff format .

cd ../frontend
npm install && npm run dev       # http://localhost:5173, прокси на Django :8000
```

Ветки: `feature/<эпик>-<кратко>` от `main`, сообщения коммитов — Conventional Commits.
