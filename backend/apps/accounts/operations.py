"""
Матрица ответственности: кто отвечает за административные операции платформы.

Операция — не новое право, а именованный набор существующих прав с ответственными ролями и местом,
где она выполняется. Права ролей задаются в roles.py; test_operations проверяет, что у каждой
ответственной роли права операции действительно есть, а у остальных ролей — нет. Так матрица
в документации, в разделе «Администрирование» интерфейса и в админке не расходится с проверками API.
"""

from __future__ import annotations

from dataclasses import dataclass

from .roles import ROLES, Role


@dataclass(frozen=True)
class Operation:
    code: str
    title: str
    description: str
    # ответственные роли; администратор отвечает за всё как владелец системы и в списках не повторяется
    roles: tuple[Role, ...]
    # операция доступна, если есть хотя бы одно из прав
    perms: tuple[str, ...]
    # где выполняется: страница интерфейса и (или) раздел админки (путь от /admin/)
    page: str | None = None
    admin: str | None = None
    # контур, в котором выполняется операция: combat — основная система, training — учебный контур
    contour: str = "combat"
    # в каких пределах: «зона» — только своя зона ответственности, «район» — все объекты
    scope: str = "район"


OPERATIONS: tuple[Operation, ...] = (
    Operation(
        "objects.add",
        "Добавление новых объектов",
        "Новый объект в дереве района: из справочника заказчика или вручную по контуру здания на карте",
        (Role.ANALYST,),
        ("topology.add_node",),
        page="/structure",
        admin="topology/node/",
    ),
    Operation(
        "objects.edit",
        "Редактирование объектов",
        "Название, критичность, контур здания, перенос объекта в другую зону",
        (Role.HEAD, Role.ANALYST),
        ("topology.change_node",),
        page="/structure",
        admin="topology/node/",
        scope="зона",
    ),
    Operation(
        "objects.fitout",
        "Обустройство объектов",
        "Границы и смежность зон ответственности, размещение датчиков на объекте",
        (Role.HEAD,),
        ("topology.manage_zones",),
        page="/structure",
        admin="topology/node/",
        scope="зона",
    ),
    Operation(
        "equipment.maintain",
        "Реестр оборудования и план ТО",
        "Единицы оборудования объекта, осмотры и состояние, план профилактических работ, заявки на ТО",
        (Role.MAINTENANCE_ENGINEER, Role.HEAD),
        ("assets.change_equipment", "workorders.plan_maintenance"),
        page="/maintenance",
        admin="assets/equipment/",
    ),
    Operation(
        "sensors.manage",
        "Управление датчиками",
        "Новые каналы, привязка к объекту и пикету, тип датчика, вывод канала из работы",
        (Role.ANALYST,),
        ("assets.add_channel",),
        page="/structure",
        admin="assets/channel/",
    ),
    Operation(
        "sensors.contracts",
        "Управление контрактами датчиков",
        "Контракт данных датчика: шаблон формата сообщения в конструкторе, профиль, правила состояний, пороги, "
        "служебные коды, приём от шлюза",
        (Role.ANALYST,),
        ("normalization.change_sensorprofile", "ingestion.change_datasource"),
        page="/constructor",
        admin="normalization/sensorprofile/",
    ),
    Operation(
        "kb.add",
        "Добавление информационных материалов",
        "Новые статьи вики: регламенты, памятки, разборы случаев — черновиком до публикации",
        (Role.HEAD, Role.ANALYST),
        ("wiki.add_wikipage",),
        page="/wiki",
        admin="wiki/wikipage/add/",
    ),
    Operation(
        "kb.manage",
        "Ведение информационной базы",
        "Разделы, публикация и снятие статей, адресация по ролям, удаление устаревшего",
        (Role.HEAD,),
        ("wiki.change_wikisection",),
        page="/wiki",
        admin="wiki/",
    ),
    Operation(
        "training.manage",
        "Управление учебным контуром",
        "Учения: сценарий, участники, старт и остановка, разбор; сценарии симулятора на полигоне",
        (Role.HEAD,),
        ("training.add_exercise",),
        page="/exercises",
        admin="training/",
        contour="training",
        scope="зона",
    ),
    Operation(
        "staff.assign",
        "Расстановка сотрудников по зонам",
        "Закрепление сотрудников за зонами и командирование в соседние зоны",
        (Role.HEAD,),
        ("accounts.assign_staff",),
        page="/structure",
        scope="зона",
    ),
    Operation(
        "integrations.manage",
        "Настройка интеграций",
        "Режимы адаптеров help desk, реестра оборудования, каталога и видеонаблюдения, проверка связи",
        (Role.ADMIN,),
        ("integrations.manage_integrations",),
        page="/integrations",
    ),
    Operation(
        "users.admin",
        "Администрирование пользователей и ролей",
        "Учётные записи, роли, команды и командная вертикаль; синхронизация с каталогом (LDAP/AD)",
        (Role.ADMIN,),
        ("accounts.change_user", "auth.change_group"),
        admin="accounts/user/",
    ),
)

BY_CODE = {op.code: op for op in OPERATIONS}


def available(user, op: Operation) -> bool:
    return bool(user.is_superuser or any(user.has_perm(p) for p in op.perms))


def operations_for(user) -> list[Operation]:
    return [op for op in OPERATIONS if available(user, op)]


def can_use_admin(user) -> bool:
    """В админку пускаем по роли, а не по флагу is_staff: он не нужен, если есть хоть одна операция."""
    if not (user and user.is_authenticated and user.is_active):
        return False
    return bool(user.is_staff or user.is_superuser or operations_for(user))


def matrix() -> list[dict]:
    """Кто за что отвечает — для раздела «Администрирование» и документации."""
    return [
        {
            "code": op.code,
            "title": op.title,
            "description": op.description,
            "responsible": [r.value for r in op.roles],
            "contour": op.contour,
            "scope": op.scope,
        }
        for op in OPERATIONS
    ]


def roles_title() -> dict[str, str]:
    return {r.value: spec.title for r, spec in ROLES.items()}
