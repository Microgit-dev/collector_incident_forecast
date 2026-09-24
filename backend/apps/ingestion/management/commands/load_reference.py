from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.accounts.demo import attach_missing_scopes
from apps.assets.registry import emulate_registry
from apps.assets.services import import_channels
from apps.topology.services import import_objects


class Command(BaseCommand):
    help = "Загрузка справочников заказчика: дерево объектов и каналы (идемпотентно)"

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(settings.DATA_DIR / "dataset"))

    def handle(self, *args, dir, **options):
        base = Path(dir)
        self.stdout.write(f"objects: {import_objects(base / 'справочник_объектов_диспетчер.csv')}")
        self.stdout.write(f"channels: {import_channels(base / 'справочник_каналов_датчиков.csv')}")
        self.stdout.write(f"equipment: {emulate_registry()}")
        self.stdout.write(f"team scopes attached: {attach_missing_scopes()}")
        self.stdout.write(self.style.SUCCESS("reference loaded"))
