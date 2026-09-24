from datetime import date

from django.core.management.base import BaseCommand

from apps.incidents import emulation


class Command(BaseCommand):
    help = (
        "Эмуляция дежурных смен для демонстрации аналитики: реальные эпизоды периода → карточки, "
        "демо-диспетчеры их отрабатывают. Всё помечено «эмуляция», в обучение не попадает."
    )

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="start", type=date.fromisoformat)
        parser.add_argument("--to", dest="end", type=date.fromisoformat)
        parser.add_argument("--seed", type=int, default=7)
        parser.add_argument("--clear", action="store_true", help="удалить ранее эмулированные карточки")

    def handle(self, *args, start=None, end=None, seed=7, clear=False, **options):
        if clear:
            self.stdout.write(f"удалено эмулированных карточек: {emulation.clear()}")
        if start and end:
            stats = emulation.emulate(start, end, seed=seed, echo=self.stdout.write)
            self.stdout.write(self.style.SUCCESS(str(stats)))
