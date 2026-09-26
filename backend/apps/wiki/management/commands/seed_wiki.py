from django.core.management.base import BaseCommand

from apps.wiki.content import seed


class Command(BaseCommand):
    help = "Начальные статьи вики (существующие не трогает; --force — перезаписать из файлов)"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        self.stdout.write(f"wiki: {seed(force=options['force'])}")
