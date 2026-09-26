from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _user_from_token(raw: str):
    from rest_framework_simplejwt.authentication import JWTAuthentication
    from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

    auth = JWTAuthentication()
    try:
        return auth.get_user(auth.get_validated_token(raw))
    except (InvalidToken, TokenError):
        return AnonymousUser()


SUBPROTOCOL = "jwt"


def token_from_subprotocols(subprotocols: list[str]) -> str | None:
    """Интерфейс открывает сокет с протоколами ["jwt", <токен>]."""
    if len(subprotocols) >= 2 and subprotocols[0] == SUBPROTOCOL:
        return subprotocols[1]
    return None


class JWTAuthMiddleware(BaseMiddleware):
    """
    Браузер не умеет ставить Authorization на WebSocket, поэтому JWT идёт в заголовке
    Sec-WebSocket-Protocol, а не в адресе: адрес с ?token= попадал бы в журналы сервера и прокси.
    """

    async def __call__(self, scope, receive, send):
        token = token_from_subprotocols(scope.get("subprotocols") or [])
        scope["user"] = await _user_from_token(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)
