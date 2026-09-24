# Прогноз инцидентов инженерных коллекторов

Сервис прогнозирования технических отказов датчиков и раннего выявления риска инцидентов
(пожар, загазованность, подтопление, несанкционированный доступ) с ролевой моделью
и вертикалью управления: от сигнала датчика до решения диспетчера и заявки бригаде.

Задача — «8. ДЖКХ» (АО «Москоллектор»). Дорожная карта и статусы — [ROADMAP.md](ROADMAP.md).

## Быстрый старт

Нужен Docker с Compose v2. Всё разворачивается локально, внешние сервисы не требуются.
Ресурсы: 4 ядра, **не менее 8 ГБ памяти для Docker** (в Docker Desktop: Settings → Resources),
~25 ГБ диска при полном импорте истории (исходные журналы 14 ГБ + архив 2,6 ГБ + БД ~2 ГБ).

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
- демо-сотрудники по командам, пароль `Passw0rd!` (входят и через LDAP, и локально):

| Команда | Зона | Сотрудники (роль) |
|---|---|---|
| Руководство района | весь район | `head.sidorova` (руководитель) |
| ОДС района | весь район | `ods.ivanov`, `ods.kozlova` (диспетчер ОДС) |
| Диспетчерская объекта Мю / Кси / Тау | объект | `disp.petrov` / `disp.nikolaev` / `disp.fedorova` (диспетчер подразделения) |
| Бригада № 1 / 2 / 3 | объект | `brigade.smirnov` / `brigade.popov` / `brigade.egorov` (бригада) |
| Аналитическая группа | весь район | `analyst.kuznetsov` (аналитик) |
| Администрирование и смежные службы | весь район | `admin.volkov` (администратор), `observer.orlova` (наблюдатель) |

Командная вертикаль: бригада → диспетчерская объекта → ОДС → руководство. Инцидент попадает
диспетчерской своего объекта, без реакции эскалируется в ОДС. В LDAP код команды хранится
в `departmentNumber`, при входе из него берутся команда и зона ответственности.
Каталог `infra/ldap/bootstrap.ldif` генерируется из `apps/accounts/demo.py` командой `manage.py demo_ldif`.
Для эксплуатации демо-состав отключается переменной `DEMO_USERS=false`.

Сырые данные заказчика кладутся в `data/` (в git не хранятся), см. [data/README.md](data/README.md).

### Данные

Стенд поставляется без данных заказчика. Их можно загрузить двумя способами.

1. **Из интерфейса** — раздел «Загрузка данных» (роли «Аналитик» и «Администратор»):
   справочники файлами или из каталога данных, журналы — выбором лет из каталога
   `data/dataset/journals/` или загрузкой CSV/XLSX через браузер. Прогресс каждого этапа виден на экране,
   импорт идёт фоновой задачей, поэтому страницу можно закрыть.
2. **Из консоли** (та же логика, прогресс печатается в терминал):

```bash
docker compose run --rm backend python manage.py import_history            # все годы, кроме 2021
docker compose run --rm backend python manage.py import_history --years 2025 2026 --raw-days 30
```

Если файлы справочников лежат в `data/dataset/` при первом запуске, они загружаются автоматически.
Импорт занимает около 1–2 минут на год журнала, пиковая память — около 2,3 ГБ.

Результат: Parquet-архив в `artifacts/archive/`, суточная витрина за всю историю, сырые показания
за оперативное окно и отчёт о качестве загрузки (интерфейс → «Качество данных»).
Решение по контурам хранения описано в [docs/adr/0001-storage-contours.md](docs/adr/0001-storage-contours.md).

### Прогноз

После первого импорта истории модель отказа датчиков обучается и первый прогноз строится автоматически.
Дальше прогноз пересчитывается раз в 15 минут. Переобучение, второй горизонт (7 суток) и бэктест
запускаются в разделе «Модели» или из консоли:

```bash
docker compose exec worker python manage.py train_model --task sensor_failure   # также gas, flood
docker compose exec worker python manage.py forecast --backtest 2026-06-01T23:59:59+03:00 2026-06-29T23:59:59+03:00
```

Методика, метрики на отложенном 2026 годе и ограничения описаны в [docs/forecasting.md](docs/forecasting.md);
сценарии газа, подтопления, пожара и НСД, рекомендации по ТО и разбор эпизодов — в [docs/scenarios.md](docs/scenarios.md),
склейка сигналов, гипотезы и приоритет — в [docs/correlation.md](docs/correlation.md).
Метрики диспетчеров и качества прогнозов, эмуляция смен, отчёты PDF/XLSX и дашборд Grafana — в
[docs/analytics.md](docs/analytics.md).

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
