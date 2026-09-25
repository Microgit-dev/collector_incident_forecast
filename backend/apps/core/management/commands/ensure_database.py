import psycopg
from django.conf import settings
from django.core.management.base import BaseCommand
from psycopg import sql


class Command(BaseCommand):
    help = "Создаёт базу из DATABASE_URL, если её нет (учебный контур живёт в отдельной базе того же сервера)"

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        if "postgresql" not in db["ENGINE"]:
            return
        params = {
            "host": db["HOST"],
            "port": db["PORT"] or 5432,
            "user": db["USER"],
            "password": db["PASSWORD"],
        }
        with psycopg.connect(dbname="postgres", autocommit=True, **params) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", [db["NAME"]]).fetchone()
            if exists:
                self.stdout.write(f"database {db['NAME']} exists")
                return
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db["NAME"])))
            self.stdout.write(self.style.SUCCESS(f"database {db['NAME']} created"))
