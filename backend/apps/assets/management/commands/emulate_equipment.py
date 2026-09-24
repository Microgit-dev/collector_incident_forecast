from django.core.management.base import BaseCommand

from apps.assets.registry import emulate_registry


class Command(BaseCommand):
    help = "Пересоздаёт эмулированный реестр оборудования по справочнику каналов (source=emulated)"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(f"equipment: {emulate_registry()}"))
