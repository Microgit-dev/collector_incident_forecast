"""
Админка платформы: разделы по зонам ответственности вместо двадцати приложений подряд.

- Главная страница начинается с «Ваших задач» — операций роли из матрицы accounts/operations.py.
- Модели сгруппированы в разделы (объекты, датчики и контракты, информационная база, учебный контур,
  пользователи и роли…); каждый видит только разделы, на модели которых у него есть права.
- Служебные модели (расписания Celery, журнал токенов) скрыты: они настраиваются bootstrap.
- Вход — тем же сеансом, что и в интерфейсе (POST /api/v1/auth/admin-session/), без второго пароля:
  страница входа админки отправляет на вход платформы. Резервный вход — /admin/login/?direct=1.
- Пускаем по операциям роли (can_use_admin), флаг is_staff вручную выставлять не нужно.
"""

from __future__ import annotations

from urllib.parse import quote

from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

# (код, название, модели «app_label.Model»; «app_label.*» — все модели модуля)
SECTIONS: list[tuple[str, str, list[str]]] = [
    ("objects", "Объекты и зоны — обустройство", ["topology.Node", "assets.Equipment"]),
    (
        "sensors",
        "Датчики и контракты данных",
        [
            "assets.Channel",
            "assets.SensorType",
            "normalization.SensorProfile",
            "normalization.StateRule",
            "ingestion.DataSource",
        ],
    ),
    ("kb", "Информационная база", ["wiki.WikiSection", "wiki.WikiPage"]),
    ("training", "Учебный контур", ["training.*"]),
    ("users", "Пользователи и роли", ["accounts.User", "accounts.Team", "auth.Group"]),
    ("forecasting", "Прогнозы и модели", ["forecasting.*"]),
    ("operations", "Инциденты и заявки", ["incidents.*", "workorders.*"]),
]
SERVICE = ("service", "Журналы и служебное")

# Служебные модели, которые в админке только мешают: их заполняет bootstrap и сама система
HIDDEN = [
    "django_celery_beat.ClockedSchedule",
    "django_celery_beat.CrontabSchedule",
    "django_celery_beat.SolarSchedule",
    "django_celery_beat.IntervalSchedule",
    "token_blacklist.OutstandingToken",
    "token_blacklist.BlacklistedToken",
]


def _section_of(app_label: str, object_name: str) -> str:
    key = f"{app_label}.{object_name}"
    for code, _title, models in SECTIONS:
        if key in models or f"{app_label}.*" in models:
            return code
    return SERVICE[0]


def _order(app_label: str, object_name: str) -> int:
    key = f"{app_label}.{object_name}"
    for _code, _title, models in SECTIONS:
        if key in models:
            return models.index(key)
    return 100


class PlatformAdminSite(admin.AdminSite):
    site_header = "Прогноз инцидентов — администрирование"
    site_title = "Прогноз инцидентов"
    index_title = "Администрирование"
    index_template = "admin/platform_index.html"

    @property
    def site_url(self):
        from django.conf import settings

        return settings.CONTOUR_URLS.get(settings.CONTOUR, "/")

    def has_permission(self, request):
        from apps.accounts.operations import can_use_admin

        return can_use_admin(request.user)

    def login(self, request, extra_context=None):
        """Вход в админку — это вход в платформу: без второго пароля и без отдельной формы."""
        if request.method == "GET" and not request.GET.get("direct"):
            from django.conf import settings

            target = request.GET.get("next") or reverse("admin:index", current_app=self.name)
            # за префиксом подсистемы (/training/) Django отдаёт next без него — возвращаем префикс
            prefix = (getattr(settings, "FORCE_SCRIPT_NAME", None) or "").rstrip("/")
            if prefix and not target.startswith(f"{prefix}/"):
                target = f"{prefix}{target}"
            return redirect(f"/login?next={quote(target)}")
        return super().login(request, extra_context)

    def get_app_list(self, request, app_label=None):
        if app_label:
            return super().get_app_list(request, app_label)
        app_dict = self._build_app_dict(request)
        titles = dict((code, title) for code, title, _ in SECTIONS) | {SERVICE[0]: SERVICE[1]}
        sections: dict[str, dict] = {}
        for app in app_dict.values():
            for model in app["models"]:
                code = _section_of(app["app_label"], model["object_name"])
                section = sections.setdefault(
                    code,
                    {
                        "name": titles[code],
                        "app_label": code,
                        "app_url": "",
                        "has_module_perms": True,
                        "models": [],
                    },
                )
                section["models"].append({**model, "_app": app["app_label"]})
        order = [code for code, _t, _m in SECTIONS] + [SERVICE[0]]
        result = []
        for code in order:
            if code in sections:
                section = sections[code]
                section["models"].sort(key=lambda m: (_order(m["_app"], m["object_name"]), m["name"]))
                result.append(section)
        return result

    def index(self, request, extra_context=None):
        from apps.accounts.operations import operations_for

        prefix = reverse("admin:index", current_app=self.name)
        tasks = [
            {"title": op.title, "description": op.description, "url": f"{prefix}{op.admin}"}
            for op in operations_for(request.user)
            if op.admin
        ]
        return super().index(request, {"my_operations": tasks, **(extra_context or {})})
