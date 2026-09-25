# Перечень библиотек и компонентов

Сформирован автоматически из установленных пакетов (`docs/delivery/gen_libraries.py`). Полный граф зависимостей с точными версиями зафиксирован в `backend/uv.lock` и `frontend/package-lock.json`.

## Backend (Python 3.12)

| Библиотека | Версия | Лицензия | Назначение |
|---|---|---|---|
| django | 5.2.17 | BSD-3-Clause | веб-фреймворк, ORM, админка, RBAC |
| djangorestframework | 3.18.1 | BSD-3-Clause | REST API |
| djangorestframework-simplejwt | 5.5.1 | MIT License | JWT-аутентификация |
| drf-spectacular | 0.30.0 | BSD-3-Clause | OpenAPI / Swagger |
| django-filter | 26.1 | BSD License | фильтры API |
| django-cors-headers | 4.9.0 | MIT | CORS |
| django-environ | 0.14.0 | MIT | настройки из окружения |
| whitenoise | 6.12.0 | MIT | раздача статики |
| psycopg | 3.3.6 | LGPL-3.0-only | драйвер PostgreSQL |
| redis | 6.4.0 | MIT | клиент Redis |
| django-treebeard | 7.0.2 | Apache-2.0 | дерево объектов (materialized path) |
| django-auditlog | 3.4.1 | MIT License | история изменений моделей |
| celery | 5.6.3 | BSD-3-Clause | фоновые и периодические задачи |
| django-celery-beat | 2.9.0 | BSD License | расписание задач в БД |
| channels | 4.3.2 | BSD License | WebSocket-уведомления |
| channels-redis | 4.3.0 | BSD | слой каналов на Redis |
| uvicorn | 0.53.0 | BSD-3-Clause | ASGI-сервер |
| confluent-kafka | 2.15.1 | Apache Software License | клиент Kafka |
| django-prometheus | 2.5.0 | Apache Software License | метрики Prometheus |
| polars | 1.44.2 | MIT License | обработка данных, признаки |
| pyarrow | 25.0.1 | Apache-2.0 | Parquet-архив |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | численные расчёты |
| scikit-learn | 1.9.1 | BSD-3-Clause | метрики качества моделей |
| lightgbm | 4.7.0 | MIT | градиентный бустинг — модели прогноза |
| joblib | 1.6.0 | BSD-3-Clause | сериализация |
| httpx | 0.28.1 | BSD License | HTTP-клиент интеграций |
| openpyxl | 3.1.5 | MIT License | XLSX: импорт журналов и отчёты |
| fpdf2 | 2.8.8 | LGPL-3.0-only | PDF-отчёты |
| djangorestframework-xml | 2.0.0 | BSD License |  |
| ruff | 0.16.8 | MIT | линтер и форматирование (разработка) |
| pytest | 9.1.1 | MIT | тесты (разработка) |
| pytest-django | 4.14.0 | BSD License | тесты Django (разработка) |
| factory-boy | 3.3.3 | MIT License | тестовые данные (разработка) |
| django-auth-ldap | 5.3.0 | BSD-2-Clause | вход через LDAP / AD |

## Frontend (TypeScript)

| Библиотека | Версия | Лицензия | Назначение |
|---|---|---|---|
| @mantine/charts | 9.6.2 | MIT | графики |
| @mantine/core | 9.6.2 | MIT | компоненты интерфейса |
| @mantine/dates | 9.6.2 | MIT | выбор дат |
| @mantine/hooks | 9.6.2 | MIT | хуки интерфейса |
| @mantine/notifications | 9.6.2 | MIT | уведомления |
| @tabler/icons-react | 3.48.0 | MIT | иконки |
| @tanstack/react-query | 5.103.2 | MIT | загрузка и кеш данных API |
| dayjs | 1.11.23 | MIT | даты и время |
| react | 19.3.0 | MIT | интерфейс |
| react-dom | 19.3.0 | MIT | интерфейс |
| react-router-dom | 7.18.4 | MIT | маршрутизация SPA |
| recharts | 3.10.1 | MIT | графики (основа @mantine/charts) |
| @vitejs/plugin-react | 6.1.1 | MIT | сборка (разработка) |
| oxlint | 1.85.0 | MIT | линтер (разработка) |
| postcss | 8.5.28 | MIT | стили (сборка) |
| postcss-preset-mantine | 1.18.0 | MIT | стили (сборка) |
| postcss-simple-vars | 7.0.1 | MIT | стили (сборка) |
| typescript | 6.0.3 | Apache-2.0 | типизация (сборка) |
| vite | 8.3.0 | MIT | сборка (разработка) |

## Компоненты инфраструктуры (образы Docker)

| Образ | Тег | Назначение |
|---|---|---|
| apache/kafka | 3.9.1 | поток событий СМВУ (KRaft, без ZooKeeper) |
| danihodovic/celery-exporter | 0.12.2 | метрики Celery |
| grafana/grafana | 12.1.0 | дашборды мониторинга и бизнес-показателей |
| oliver006/redis_exporter | v1.92.0 | метрики Redis |
| osixia/openldap | 1.5.0 | тестовый каталог LDAP (эмуляция AD заказчика) |
| prodrigestivill/postgres-backup-local | 16 | ежедневные резервные копии pg_dump |
| prom/prometheus | v3.5.0 | сбор метрик |
| prometheuscommunity/postgres-exporter | v0.20.1 | метрики PostgreSQL |
| provectuslabs/kafka-ui | v0.7.2 | просмотр топиков Kafka |
| redis | 7-alpine | брокер Celery, кеш, слой каналов WebSocket |
| timescale/timescaledb | latest-pg16 | PostgreSQL 16 + TimescaleDB — основное хранилище |

Собственные образы: `collector-forecast/backend` (Django, Celery, консьюмер Kafka — одна сборка), `collector-forecast/web` (Caddy с собранным интерфейсом, TLS), `collector-forecast/mock-helpdesk` (эмулятор системы заявок, только стандартная библиотека Python). Внешние платные сервисы и облачные API не используются; единственный внешний источник — открытый API Open-Meteo (без ключа), без него система работает, теряя только погодные признаки.
