from django.core.management.base import BaseCommand

from apps.accounts import lockout
from apps.audit.models import ActionLog


class Command(BaseCommand):
    help = "Снять блокировку входа после серии неудачных попыток (не дожидаясь 15 минут)"

    def add_arguments(self, parser):
        parser.add_argument("usernames", nargs="+", help="логины, как их вводят при входе")

    def handle(self, *args, usernames, **options):
        for username in usernames:
            count = lockout.attempts(username)
            lockout.reset(username)
            # консольное действие администратора сервера — в журнал, как и сама блокировка
            ActionLog.objects.create(
                action="security.unlock",
                path="manage.py unlock",
                object_repr=username,
                payload={"attempts": count},
            )
            self.stdout.write(f"{username}: неудачных попыток было {count}, счётчик сброшен")
