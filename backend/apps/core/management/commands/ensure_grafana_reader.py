"""
Роль БД только для чтения, под которой Grafana ходит в TimescaleDB.

В Grafana OSS любой пользователь с ролью Viewer может отправить в источник данных произвольный
SQL (API /api/ds/query), поэтому источник подключается не владельцем базы, а этой ролью:
SELECT только на таблицы панелей, из учётных записей — только ФИО, транзакции только на чтение.
Идемпотентна, вызывается из bootstrap в рабочем контуре.
"""

import os

from django.core.management.base import BaseCommand
from django.db import connection
from psycopg import sql

# Таблицы, которые читают панели infra/grafana/dashboards (бизнес и системная)
TABLES = [
    "incidents_incident",
    "incidents_decision",
    "incidents_incidentevent",
    "forecasting_prediction",
    "telemetry_channelstate",
    "telemetry_reading",
]
# Из учётных записей — только для подписи «сотрудник» (без логина, почты и хеша пароля)
USER_COLUMNS = ["id", "first_name", "last_name"]


class Command(BaseCommand):
    help = "Создаёт или обновляет роль БД только для чтения для источника данных Grafana"

    def handle(self, *args, **options):
        role = os.environ.get("GRAFANA_DB_USER", "grafana_reader")
        password = os.environ.get("GRAFANA_DB_PASSWORD")
        if not password:
            self.stdout.write("grafana reader: GRAFANA_DB_PASSWORD не задан, пропущено")
            return
        ident = sql.Identifier(role)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
            verb = "ALTER" if cursor.fetchone() else "CREATE"
            cursor.execute(
                sql.SQL(verb + " ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                    ident, sql.Literal(password)
                )
            )
            cursor.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(ident))
            cursor.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '30s'").format(ident))
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(connection.settings_dict["NAME"]), ident
                )
            )
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(ident))
            cursor.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(ident))
            for table in TABLES:
                cursor.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(sql.Identifier(table), ident))
            cursor.execute(
                sql.SQL("GRANT SELECT ({}) ON accounts_user TO {}").format(
                    sql.SQL(", ").join(map(sql.Identifier, USER_COLUMNS)), ident
                )
            )
        self.stdout.write(f"grafana reader: {role} ({verb.lower()}), таблиц {len(TABLES) + 1}")
