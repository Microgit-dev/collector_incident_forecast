"""
Каталог интеграций для страницы «Интеграции» (администратор): режим работы (эмуляция стенда или
боевое подключение), адрес, последний успешный обмен и ошибка, проверка связи и ручной запуск
синхронизации. Каждая проверка — только чтение.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from django.conf import settings
from django.utils import timezone

from .clients import conf
from .models import IntegrationState

logger = logging.getLogger(__name__)


def mark(code: str, ok: bool, result: dict | None = None, error: str = "") -> None:
    """Записать итог обмена: вызывают клиенты и задачи синхронизации."""
    now = timezone.now()
    fields: dict = {"last_result": result or {}}
    if ok:
        fields["last_ok_at"] = now
    else:
        fields.update(last_error_at=now, last_error=error[:2000])
    IntegrationState.objects.update_or_create(code=code, defaults=fields)


@dataclass(frozen=True)
class Integration:
    code: str
    title: str
    purpose: str
    mode: Callable[[], str]
    endpoint: Callable[[], str]
    check: Callable[[], dict]
    sync: Callable[[], dict] | None = None
    sync_label: str = "Синхронизировать"
    modes: dict[str, str] = field(default_factory=dict)


# ---------- проверки ----------


def _smvu_check() -> dict:
    from confluent_kafka.admin import AdminClient

    from apps.telemetry.models import Reading

    topics = (
        AdminClient({"bootstrap.servers": settings.KAFKA["BOOTSTRAP_SERVERS"]}).list_topics(timeout=5).topics
    )
    topic = settings.KAFKA["TOPIC_RAW_EVENTS"]
    last = Reading.objects.order_by("-ts").values_list("ts", flat=True).first()
    return {
        "topic": topic,
        "topic_exists": topic in topics,
        "last_event_at": last.isoformat() if last else None,
    }


def _ldap_check() -> dict:
    if not getattr(settings, "AUTH_LDAP_SERVER_URI", None):
        return {"enabled": False}
    import ldap

    conn = ldap.initialize(settings.AUTH_LDAP_SERVER_URI)
    conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
    for option, value in getattr(settings, "AUTH_LDAP_GLOBAL_OPTIONS", {}).items():
        conn.set_option(option, value)
    if settings.AUTH_LDAP_START_TLS:
        conn.start_tls_s()
    conn.simple_bind_s(settings.AUTH_LDAP_BIND_DN, settings.AUTH_LDAP_BIND_PASSWORD)
    search = settings.AUTH_LDAP_USER_SEARCH
    users = conn.search_s(search.base_dn, ldap.SCOPE_SUBTREE, "(objectClass=person)", ["cn"])
    groups = settings.AUTH_LDAP_GROUP_SEARCH
    roles = conn.search_s(groups.base_dn, ldap.SCOPE_SUBTREE, groups.filterstr, ["cn"])
    conn.unbind_s()
    return {"users": len(users), "groups": len(roles)}


def _helpdesk_check() -> dict:
    from .clients import HelpdeskClient

    if conf("HELPDESK_MODE") == "off":
        return {"enabled": False}
    return HelpdeskClient().ping()


def _helpdesk_sync() -> dict:
    from apps.workorders.services import sync_external

    return sync_external()


def _registry_check() -> dict:
    from django.db.models import Count

    from apps.assets.models import Equipment

    result = {
        "equipment": dict(Equipment.objects.values_list("source").annotate(n=Count("pk")).order_by()),
    }
    if conf("REGISTRY_MODE") == "api":
        from .clients import RegistryClient

        result["remote_rows"] = len(RegistryClient().rows())
    return result


def _registry_sync() -> dict:
    from apps.assets.registry_sync import sync_from_api

    return sync_from_api()


def _vms_check() -> dict:
    from apps.assets.models import Camera

    from .clients import VideoClient

    result = {"cameras": Camera.objects.filter(is_active=True).count()}
    if conf("VMS_MODE") != "off":
        result.update(VideoClient().ping())
    return result


def _weather_check() -> dict:
    from .clients import WeatherClient
    from .models import WeatherDaily

    today = timezone.localdate()
    hours = len(WeatherClient().hourly(today, today).get("hourly", {}).get("time", []))
    last = WeatherDaily.objects.order_by("-day").values_list("day", flat=True).first()
    return {"hours_today": hours, "last_day": last.isoformat() if last else None}


def _weather_sync() -> dict:
    from .weather import sync_recent

    return {"days": sync_recent()}


def _observability_check() -> dict:
    import httpx

    prometheus = httpx.get("http://prometheus:9090/prometheus/-/healthy", timeout=5)
    grafana = httpx.get("http://grafana:3000/grafana/api/health", timeout=5)
    return {"prometheus": prometheus.status_code, "grafana": grafana.json().get("database")}


INTEGRATIONS: list[Integration] = [
    Integration(
        "smvu",
        "Система мониторинга СМВУ",
        "Поток событий датчиков в режиме, близком к реальному времени (ТЗ §7, §13). Только чтение.",
        mode=lambda: "kafka",
        endpoint=lambda: f"{settings.KAFKA['BOOTSTRAP_SERVERS']} · {settings.KAFKA['TOPIC_RAW_EVENTS']}",
        check=_smvu_check,
        modes={"kafka": "очередь сообщений Kafka (шлюз СМВУ заказчика или эмулятор потока)"},
    ),
    Integration(
        "ldap",
        "Служба каталогов LDAP / AD",
        "Вход по учётной записи домена, роли — группы каталога, команда — departmentNumber (ТЗ §11).",
        mode=lambda: (
            ("ad" if "ldaps" in getattr(settings, "AUTH_LDAP_SERVER_URI", "") else "ldap")
            if getattr(settings, "AUTH_LDAP_SERVER_URI", None)
            else "off"
        ),
        endpoint=lambda: getattr(settings, "AUTH_LDAP_SERVER_URI", ""),
        check=_ldap_check,
        modes={
            "ldap": "LDAP (на стенде — тестовый каталог openldap)",
            "ad": "Active Directory по LDAPS",
            "off": "выключено: локальные учётные записи",
        },
    ),
    Integration(
        "helpdesk",
        "Система учёта заявок (help desk)",
        "Передача утверждённых заявок и получение их статусов и отчётов исполнителя (ТЗ §6, §10).",
        mode=lambda: conf("HELPDESK_MODE"),
        endpoint=lambda: conf("HELPDESK_URL"),
        check=_helpdesk_check,
        sync=_helpdesk_sync,
        sync_label="Забрать статусы",
        modes={
            "mock": "эмулятор стенда mock-helpdesk",
            "rest": "help desk заказчика по REST",
            "off": "выключено",
        },
    ),
    Integration(
        "registry",
        "Реестр оборудования",
        "Учётный список оборудования: наработка, регламент ТО, ввод в эксплуатацию (ТЗ §6, §10, §13).",
        mode=lambda: conf("REGISTRY_MODE"),
        endpoint=lambda: conf("REGISTRY_URL") or "—",
        check=_registry_check,
        sync=lambda: (
            _registry_sync()
            if conf("REGISTRY_MODE") == "api"
            else {"detail": "синхронизация по API выключена"}
        ),
        sync_label="Синхронизировать реестр",
        modes={
            "emulated": "эмуляция по каналам (реестра у заказчика пока нет)",
            "api": "учётная система заказчика по API, раз в сутки",
            "file": "выгрузки CSV/XLSX из учётной системы",
        },
    ),
    Integration(
        "vms",
        "Видеонаблюдение",
        "Кадры камер у места тревоги для проверки диспетчером (ТЗ §12, шаг «Верификация»). Только чтение.",
        mode=lambda: conf("VMS_MODE"),
        endpoint=lambda: conf("VMS_URL"),
        check=_vms_check,
        modes={
            "mock": "эмулятор стенда mock-vms",
            "http": "система видеонаблюдения заказчика",
            "off": "выключено",
        },
    ),
    Integration(
        "weather",
        "Метеоданные Open-Meteo",
        "Осадки, температура, снежный покров — признаки прогноза подтоплений (ТЗ §13).",
        mode=lambda: "open-meteo",
        endpoint=lambda: conf("WEATHER_URL"),
        check=_weather_check,
        sync=_weather_sync,
        sync_label="Загрузить последние сутки",
        modes={"open-meteo": "открытый API без ключа"},
    ),
    Integration(
        "observability",
        "Prometheus и Grafana",
        "Метрики сервисов и бизнес-панели; вход через учётную запись системы.",
        mode=lambda: "internal",
        endpoint=lambda: "/prometheus/ · /grafana/",
        check=_observability_check,
        modes={"internal": "в составе поставки"},
    ),
]
BY_CODE = {i.code: i for i in INTEGRATIONS}


def _run(code: str, fn: Callable[[], dict]) -> dict:
    try:
        result = fn()
    except Exception as exc:  # проверка любой внешней системы: ошибка показывается администратору
        logger.warning("integration %s failed", code, exc_info=True)
        mark(code, False, error=f"{type(exc).__name__}: {exc}")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    mark(code, True, result)
    return {"ok": True, "result": result}


def check(code: str) -> dict:
    return _run(code, BY_CODE[code].check)


def sync(code: str) -> dict:
    integration = BY_CODE[code]
    if integration.sync is None:
        return {"ok": False, "error": "У интеграции нет ручной синхронизации"}
    return _run(code, integration.sync)


def overview() -> list[dict]:
    states = {s.code: s for s in IntegrationState.objects.all()}
    rows = []
    for i in INTEGRATIONS:
        state = states.get(i.code)
        mode = i.mode()
        rows.append(
            {
                "code": i.code,
                "title": i.title,
                "purpose": i.purpose,
                "mode": mode,
                "mode_label": i.modes.get(mode, mode),
                # тестовый каталог стенда (сервис openldap в compose) — тоже эмуляция
                "emulated": mode in {"mock", "emulated"} or "openldap" in i.endpoint(),
                "endpoint": i.endpoint(),
                "can_sync": i.sync is not None,
                "sync_label": i.sync_label,
                "last_ok_at": state.last_ok_at if state else None,
                "last_error_at": state.last_error_at if state else None,
                "last_error": state.last_error if state else "",
                "last_result": state.last_result if state else {},
            }
        )
    return rows
