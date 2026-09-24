from django.core.management.base import BaseCommand, CommandError

from apps.ingestion import history


class Command(BaseCommand):
    help = (
        "Импорт исторических журналов СМВУ из каталога данных: Parquet-архив, отчёт о качестве, "
        "суточная витрина за всю историю и сырые показания за оперативное окно. "
        "То же самое запускается из интерфейса: «Загрузка данных»."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--years", type=int, nargs="*", help="По умолчанию — все найденные, кроме исключённых"
        )
        parser.add_argument("--raw-days", type=int, default=30, help="Оперативное окно сырых показаний, дней")

    def handle(self, *args, years, raw_days, **options):
        found = history.available_journals()
        if not found:
            raise CommandError(f"В {history.journals_dir()} нет файлов журналов")
        selected = years or [j["year"] for j in found if not j["excluded"]]
        self.stdout.write(f"years: {selected}; excluded by default: {sorted(history.EXCLUDED_YEARS)}")
        try:
            batch = history.plan(selected, raw_days)
        except (history.ImportBusy, FileNotFoundError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        history.run_batch(batch, echo=self.stdout.write)
        self.stdout.write(self.style.SUCCESS(f"batch {batch} done"))
