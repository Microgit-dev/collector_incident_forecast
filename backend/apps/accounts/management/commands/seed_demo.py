import os

from django.core.management.base import BaseCommand

from apps.accounts.demo import seed_demo


class Command(BaseCommand):
    help = "Демо-команды и сотрудники по ролям (идемпотентно; пароль задаётся только новым учёткам)"

    def add_arguments(self, parser):
        parser.add_argument("--password", default=os.environ.get("DEMO_PASSWORD", "Passw0rd!"))

    def handle(self, *args, password, **options):
        self.stdout.write(self.style.SUCCESS(f"demo: {seed_demo(password)}"))
