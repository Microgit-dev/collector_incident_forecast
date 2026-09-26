import pytest
from asgiref.sync import async_to_sync
from rest_framework_simplejwt.tokens import AccessToken

from apps.notifications.auth import JWTAuthMiddleware, token_from_subprotocols


def test_token_is_taken_only_from_subprotocols():
    assert token_from_subprotocols(["jwt", "abc"]) == "abc"
    assert token_from_subprotocols(["abc"]) is None
    assert token_from_subprotocols([]) is None


def _user_for(scope):
    seen = {}

    async def app(scope, receive, send):
        seen["user"] = scope["user"]

    async_to_sync(JWTAuthMiddleware(app))(scope, None, None)
    return seen["user"]


@pytest.mark.django_db(transaction=True)
def test_middleware_authenticates_by_subprotocol_not_by_url(make_user):
    user = make_user("petrov", "unit_dispatcher")
    token = str(AccessToken.for_user(user))
    assert _user_for({"type": "websocket", "subprotocols": ["jwt", token], "query_string": b""}).pk == user.pk
    # токен в адресе попадал в журналы сервера — больше не принимается
    url_only = {"type": "websocket", "subprotocols": [], "query_string": f"token={token}".encode()}
    assert not _user_for(url_only).is_authenticated
