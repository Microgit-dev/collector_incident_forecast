"""
Вход в Grafana и Prometheus через учётную запись системы — без отдельных паролей.

1. Интерфейс вызывает POST /api/v1/observability/session/ со своим JWT: бэкенд ставит подписанную
   cookie на 8 часов (HttpOnly, Secure) и отвечает, какие панели доступны.
2. Caddy перед каждым запросом к /grafana/ и /prometheus/ спрашивает GET /api/v1/observability/auth/
   (forward_auth). Мы проверяем cookie, активность учётки и право роли и возвращаем заголовки
   X-WEBAUTH-*, по которым Grafana входит (auth.proxy) с ролью Admin или Viewer.

Права: accounts.view_grafana — бизнес-панели (аналитик), accounts.view_system_monitoring — системные
панели Grafana и Prometheus (администратор). Проверка выполняется на каждом запросе с кешем
на CHECK_CACHE секунд: снятая роль или заблокированная учётка теряют доступ почти сразу.

Тем же сеансом открывается веб-интерфейс симулятора датчиков (/simulator/): право training.add_exercise —
руководитель учений.
"""

from __future__ import annotations

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.http import HttpResponse
from django.views.decorators.http import require_GET
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import log_action

from .models import User

COOKIE = "cf_obs"
SALT = "observability-session"
MAX_AGE = 8 * 3600
CHECK_CACHE = 30
GRAFANA_PERM = "accounts.view_grafana"
SYSTEM_PERM = "accounts.view_system_monitoring"
SIMULATOR_PERM = "training.add_exercise"
SERVICES = {"grafana", "prometheus", "simulator"}


def access_of(user) -> dict:
    """Какие панели доступны пользователю: grafana — с какой ролью, prometheus и simulator — да/нет."""
    system = user.has_perm(SYSTEM_PERM)
    grafana = system or user.has_perm(GRAFANA_PERM)
    return {
        "grafana": grafana,
        "grafana_role": "Admin" if system else "Viewer",
        "prometheus": system,
        "simulator": user.has_perm(SIMULATOR_PERM),
    }


def _links(access: dict) -> dict:
    return {
        "grafana": "/grafana/" if access["grafana"] else None,
        "business": "/grafana/d/collector-business" if access["grafana"] else None,
        "system": "/grafana/d/collector-system" if access["prometheus"] else None,
        "prometheus": "/prometheus/" if access["prometheus"] else None,
        "simulator": "/simulator/" if access["simulator"] else None,
    }


class SessionView(APIView):
    """Открыть сеанс панелей наблюдаемости (cookie для Caddy) или закрыть его при выходе."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(_links(access_of(request.user)))

    def post(self, request):
        access = access_of(request.user)
        if not (access["grafana"] or access["simulator"]):
            return Response({"detail": "Панели мониторинга недоступны вашей роли"}, status=403)
        response = Response(_links(access))
        response.set_cookie(
            COOKIE,
            signing.TimestampSigner(salt=SALT).sign(str(request.user.pk)),
            max_age=MAX_AGE,
            httponly=True,
            secure=not settings.DEBUG,
            samesite="Lax",
        )
        log_action(request, "observability.session", payload={"role": access["grafana_role"]})
        return response

    def delete(self, request):
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(COOKIE, samesite="Lax")
        return response


def _denied(text: str, code: int) -> HttpResponse:
    page = (
        '<!doctype html><meta charset="utf-8"><title>Нет доступа</title>'
        '<body style="font-family:sans-serif;max-width:36rem;margin:4rem auto;line-height:1.5">'
        f'<h2>Нет доступа</h2><p>{text}</p><p><a href="/">Вернуться в систему</a></p></body>'
    )
    return HttpResponse(page, status=code, content_type="text/html; charset=utf-8")


def _cached_access(user_id: int) -> dict | None:
    key = f"obs:access:{user_id}"
    access = cache.get(key)
    if access is None:
        user = User.objects.filter(pk=user_id, is_active=True).first()
        access = (
            {**access_of(user), "username": user.username, "name": user.get_full_name(), "email": user.email}
            if user
            else {}
        )
        cache.set(key, access, CHECK_CACHE)
    return access or None


@require_GET
def forward_auth(request):
    """Проверка для Caddy forward_auth: 200 и заголовки X-WEBAUTH-* или страница «нет доступа»."""
    service = request.GET.get("service")
    if service not in SERVICES:
        return _denied("Неизвестная служба.", 404)
    raw = request.COOKIES.get(COOKIE)
    try:
        user_id = int(signing.TimestampSigner(salt=SALT).unsign(raw or "", max_age=MAX_AGE))
    except (signing.BadSignature, ValueError):
        return _denied("Откройте панели мониторинга из меню системы — вход выполняется автоматически.", 401)
    access = _cached_access(user_id)
    if access is None:
        return _denied("Учётная запись заблокирована или удалена.", 401)
    if not access[service]:
        return _denied("Эта панель недоступна вашей роли.", 403)
    response = HttpResponse(status=200)
    response["X-WEBAUTH-USER"] = access["username"]
    # Заголовки HTTP — латиница: имя в Grafana подставляется из логина, если ФИО не в ASCII
    response["X-WEBAUTH-NAME"] = access["name"] if access["name"].isascii() else access["username"]
    response["X-WEBAUTH-EMAIL"] = access["email"]
    response["X-WEBAUTH-ROLE"] = access["grafana_role"]
    return response
