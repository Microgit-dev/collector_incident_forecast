"""
Единый вход платформы. Учётные записи, роли и команды ведёт основная система (контур combat): только
она выдаёт токены. Учебный контур — подсистема на том же адресе (/training/), вход в неё не нужен:
тот же JWT принимается, а учётная запись берётся из основной системы (identity.py).

В токене вместо числового id — логин (USER_ID_FIELD = username): id в базах контуров разные.
Утверждение ctr — контур, выдавший токен. Принимаются только токены основной системы, поэтому
учебный контур не может выпустить токен, который пустил бы в рабочий.
"""

from __future__ import annotations

from django.conf import settings
from django.utils.translation import gettext_lazy as _
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken
from rest_framework_simplejwt.settings import api_settings

CONTOUR_CLAIM = "ctr"


def issuer() -> str:
    """Контур, который выдаёт токены и ведёт учётные записи."""
    return settings.IDENTITY_CONTOUR


def is_identity_provider() -> bool:
    return issuer() == settings.CONTOUR


class PlatformJWTAuthentication(JWTAuthentication):
    def get_validated_token(self, raw_token):
        token = super().get_validated_token(raw_token)
        if token.get(CONTOUR_CLAIM) != issuer():
            raise InvalidToken(_("Token is not issued by the platform"))
        return token

    def get_user(self, validated_token):
        if is_identity_provider():
            return super().get_user(validated_token)
        from .identity import ensure_user

        username = validated_token.get(api_settings.USER_ID_CLAIM)
        user = ensure_user(username) if username else None
        if user is None or not user.is_active:
            raise AuthenticationFailed(_("User not found"), code="user_not_found")
        return user
