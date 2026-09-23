import logging

from .services import log_action

logger = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
AUDITED_PREFIXES = ("/api/", "/admin/")


class ActionLogMiddleware:
    """
    Пишет в журнал каждый изменяющий запрос к API и админке.
    Чтения не пишем: дашборд опрашивает API постоянно, журнал превратился бы в шум.
    Пользователь берётся после отработки view — к этому моменту DRF уже аутентифицировал JWT.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.method not in SAFE_METHODS and request.path.startswith(AUDITED_PREFIXES):
            action = "auth.login" if request.path.startswith("/api/v1/auth/token") else "http.mutation"
            try:
                log_action(request, action, status_code=response.status_code)
            except Exception:  # журнал не должен ломать основной запрос
                logger.exception("failed to write action log")
        return response
