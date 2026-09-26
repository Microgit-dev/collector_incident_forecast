import contextlib

from django.conf import settings
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.audit.services import log_action

from ..lockout import is_locked, reset


class LoginView(TokenObtainPairView):
    """Вход по логину и паролю; после серии ошибок — 429, пока не истечёт блокировка."""

    def post(self, request, *args, **kwargs):
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
