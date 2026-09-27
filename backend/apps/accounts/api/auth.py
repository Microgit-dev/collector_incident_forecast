import contextlib

from django.conf import settings
from django.contrib.auth import login, logout
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.audit.services import log_action

from ..authentication import CONTOUR_CLAIM, is_identity_provider
from ..lockout import is_locked, reset
from ..operations import can_use_admin

ELSEWHERE = {"detail": "Вход выполняется в основной системе — учебный контур использует тот же вход."}


class PlatformTokenObtainSerializer(TokenObtainPairSerializer):
    """Токен помечается контуром-издателем: его принимают все подсистемы платформы."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token[CONTOUR_CLAIM] = settings.CONTOUR
        return token


class LoginView(TokenObtainPairView):
    """Вход по логину и паролю; после серии ошибок — 429, пока не истечёт блокировка."""

    def post(self, request, *args, **kwargs):
        if not is_identity_provider():
            return Response(ELSEWHERE, status=status.HTTP_403_FORBIDDEN)
        username = str(request.data.get("username", ""))
        if is_locked(username):
            log_action(request, "auth.locked", payload={"username": username[:150]}, status_code=429)
            return Response(
                {
                    "detail": f"Слишком много неудачных попыток входа. Вход заблокирован на "
                    f"{settings.LOCKOUT_MINUTES} минут — попробуйте позже или обратитесь к администратору."
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            reset(username)  # simplejwt не шлёт user_logged_in — сбросить счётчик ошибок здесь
        return response


class LogoutView(APIView):
    """Выход: refresh-токен отзывается, повторно получить по нему доступ нельзя."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # уже отозван или истёк — для выхода это не ошибка
        with contextlib.suppress(TokenError):
            RefreshToken(request.data.get("refresh", "")).blacklist()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RefreshView(TokenRefreshView):
    """Обновление токена — только в основной системе: там журнал выданных и отозванных токенов."""

    def post(self, request, *args, **kwargs):
        if not is_identity_provider():
            return Response(ELSEWHERE, status=status.HTTP_403_FORBIDDEN)
        return super().post(request, *args, **kwargs)


class AdminSessionView(APIView):
    """
    Вход в админку без второго пароля: интерфейс со своим JWT открывает сеанс Django (cookie) и
    переходит в нужный раздел. Пускаем по операциям роли (accounts/operations.py), а не по is_staff.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        if not can_use_admin(user):
            return Response({"detail": "Администрирование недоступно вашей роли"}, status=403)
        login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")
        log_action(request, "admin.session")
        prefix = getattr(settings, "FORCE_SCRIPT_NAME", None) or ""
        return Response({"url": f"{prefix}/admin/"})

    def delete(self, request):
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)
