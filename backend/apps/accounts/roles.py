"""
Ролевая модель (RBAC). Роль — это Django Group с набором permissions; код роли совпадает
с именем группы, поэтому группы из LDAP (cn=...) маппятся на роли один в один.

Видимость данных дополнительно ограничивается зоной ответственности (User.scope_node),
а право accounts.view_all_scopes снимает это ограничение (ОДС, аналитик, администратор).

Кто отвечает за административные операции (объекты, датчики, контракты датчиков, вики, учебный
контур, пользователи) — матрица в operations.py; права ниже должны ей соответствовать (test_operations).
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    HEAD = "head"
    ODS_DISPATCHER = "ods_dispatcher"
    UNIT_DISPATCHER = "unit_dispatcher"
    ANALYST = "analyst"
    TECHNICIAN = "technician"
    MAINTENANCE_ENGINEER = "maintenance_engineer"
    OBSERVER = "observer"


@dataclass(frozen=True)
class RoleSpec:
    title: str
    description: str
    # Элементы: "app_label.codename", "app_label.*" (все права модуля) или "app_label.view_*"
    perms: list[str] = field(default_factory=list)


_VIEW_ALL = [
    "topology.view_*",
    "assets.view_*",
    "normalization.view_*",
    "telemetry.view_*",
    "forecasting.view_*",
    "incidents.view_*",
    "workorders.view_*",
    "notifications.view_*",
    "analytics.view_*",
    "integrations.view_*",
]

ROLES: dict[Role, RoleSpec] = {
    Role.ADMIN: RoleSpec(
        "Администратор",
        "Настройка системы, пользователей, справочников и интеграций",
        ["*"],
    ),
    Role.HEAD: RoleSpec(
        "Руководитель подразделения",
        "Контроль инцидентов и заявок в своей зоне, утверждение заявок, отчёты",
        [
            *_VIEW_ALL,
            "incidents.change_alert",
            "incidents.acknowledge_alert",
            "incidents.decide_incident",
            "incidents.escalate_incident",
            "incidents.change_incident",
            # перехват карточки у диспетчера — только руководитель
            "incidents.takeover_incident",
            "workorders.add_workorder",
            "workorders.change_workorder",
            "workorders.approve_workorder",
            # план ТО зоны — руководитель видит и корректирует план инженера ТО
            "workorders.plan_maintenance",
            "workorders.change_maintenancerecommendation",
            "analytics.export_report",
            "notifications.change_notification",
            "audit.view_actionlog",
            # обустройство объектов своей зоны: границы и смежность зон, правка объектов, оборудование,
            # размещение датчиков; новые объекты и каналы заводит аналитик (operations.py)
            "topology.manage_zones",
            "topology.change_node",
            "assets.change_channel",
            "assets.add_equipment",
            "assets.change_equipment",
            # расстановка сотрудников по зонам и командирование
            "accounts.assign_staff",
            "accounts.view_secondment",
            # информационная база: статьи, разделы, публикация
            "wiki.*",
            # учения: сценарий, участники, старт и досрочная остановка
            "training.add_exercise",
            "training.change_exercise",
            "training.view_exercise",
        ],
    ),
    Role.ODS_DISPATCHER: RoleSpec(
        "Диспетчер ОДС",
        "Оперативная работа по всему району: алерты, инциденты, решения, черновики заявок",
        [
            *_VIEW_ALL,
            "accounts.view_all_scopes",
            "incidents.change_alert",
            "incidents.acknowledge_alert",
            "incidents.add_incident",
            "incidents.change_incident",
            "incidents.decide_incident",
            "incidents.escalate_incident",
            "workorders.add_workorder",
            "workorders.change_workorder",
            "notifications.change_notification",
        ],
    ),
    Role.UNIT_DISPATCHER: RoleSpec(
        "Диспетчер подразделения",
        "Оперативная работа в своей зоне ответственности",
        [
            *_VIEW_ALL,
            "incidents.change_alert",
            "incidents.acknowledge_alert",
            "incidents.add_incident",
            "incidents.change_incident",
            "incidents.decide_incident",
            "incidents.escalate_incident",
            "workorders.add_workorder",
            "workorders.change_workorder",
            "notifications.change_notification",
        ],
    ),
    Role.ANALYST: RoleSpec(
        "Аналитик",
        "Верификация данных и прогнозов, профили датчиков, обучение моделей, аналитика",
        [
            *_VIEW_ALL,
            "accounts.view_all_scopes",
            "normalization.*",
            "forecasting.*",
            # новые объекты и датчики, контракты датчиков (normalization.*), правка объектов
            "topology.add_node",
            "topology.change_node",
            "assets.add_channel",
            "assets.change_channel",
            # информационные материалы: статьи вики (разделы и публикацию ведёт руководитель)
            "wiki.view_*",
            "wiki.add_wikipage",
            "wiki.change_wikipage",
            "ingestion.*",
            "incidents.decide_incident",
            "analytics.export_report",
            "audit.view_actionlog",
            "notifications.change_notification",
            # бизнес-панели Grafana; системные панели и Prometheus — только администратору
            "accounts.view_grafana",
        ],
    ),
    Role.TECHNICIAN: RoleSpec(
        "Ремонтная бригада",
        "Исполнение заявок на объекте",
        [
            "topology.view_node",
            "assets.view_*",
            "workorders.view_workorder",
            "workorders.execute_workorder",
            # фактическое состояние оборудования при выполнении заявки
            "workorders.view_equipmentinspection",
            "workorders.add_equipmentinspection",
            "notifications.view_notification",
            "notifications.change_notification",
        ],
    ),
    Role.MAINTENANCE_ENGINEER: RoleSpec(
        "Инженер ТО",
        "Планирование профилактических работ: план ТО по регламенту и состоянию, реестр оборудования, "
        "фактическое состояние, черновики заявок на ТО",
        [
            *_VIEW_ALL,
            "workorders.plan_maintenance",
            "workorders.add_workorder",
            "workorders.change_workorder",
            "workorders.change_maintenancerecommendation",
            "workorders.add_equipmentinspection",
            "assets.add_equipment",
            "assets.change_equipment",
            "analytics.export_report",
            "notifications.change_notification",
        ],
    ),
    Role.OBSERVER: RoleSpec("Наблюдатель", "Только просмотр в своей зоне", _VIEW_ALL),
}
