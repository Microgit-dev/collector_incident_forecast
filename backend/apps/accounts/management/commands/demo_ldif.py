import base64
from collections import defaultdict

from django.core.management.base import BaseCommand

from apps.accounts.demo import PEOPLE, TEAMS

BASE = "dc=collector,dc=local"
HEADER = """# Тестовый каталог вместо AD заказчика. Пароль всех демо-учёток: Passw0rd!
# Сгенерирован командой `manage.py demo_ldif` из apps/accounts/demo.py — правьте там.
# Группы ou=roles маппятся на одноимённые роли, departmentNumber — код команды (зона ответственности).

dn: ou=people,{base}
objectClass: organizationalUnit
ou: people

dn: ou=roles,{base}
objectClass: organizationalUnit
ou: roles
"""


def _attr(name: str, value: str) -> str:
    if value.isascii():
        return f"{name}: {value}"
    return f"{name}:: {base64.b64encode(value.encode()).decode()}"


class Command(BaseCommand):
    help = "Печатает LDIF тестового каталога по демо-составу (infra/ldap/bootstrap.ldif)"

    def add_arguments(self, parser):
        parser.add_argument("--output", help="файл LDIF (UTF-8, LF); без него — в stdout")

    def handle(self, *args, output=None, **options):
        teams = {t.code: t for t in TEAMS}
        blocks = [HEADER.format(base=BASE)]
        members = defaultdict(list)
        for p in PEOPLE:
            dn = f"uid={p.username},ou=people,{BASE}"
            members[p.role.value].append(dn)
            lines = [
                f"dn: {dn}",
                "objectClass: inetOrgPerson",
                f"uid: {p.username}",
                _attr("cn", f"{p.first_name} {p.last_name}"),
                _attr("givenName", p.first_name),
                _attr("sn", p.last_name),
                _attr("title", p.position),
                _attr("ou", teams[p.team].name),
                f"departmentNumber: {p.team}",
                f"mail: {p.username}@collector.local",
                "userPassword: Passw0rd!",
            ]
            blocks.append("\n".join(lines) + "\n")
        for role, dns in members.items():
            lines = [f"dn: cn={role},ou=roles,{BASE}", "objectClass: groupOfNames", f"cn: {role}"]
            lines += [f"member: {dn}" for dn in dns]
            blocks.append("\n".join(lines) + "\n")
        text = "\n".join(blocks)
        if output:
            with open(output, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        else:
            self.stdout.write(text, ending="")
