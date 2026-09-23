from .models import ActionLog


def client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log_action(request, action: str, *, obj=None, payload: dict | None = None, status_code=None) -> ActionLog:
    """Явная запись бизнес-действия (решение по инциденту, экспорт отчёта, запуск обучения…)."""
    user = getattr(request, "user", None)
    authenticated = bool(user and user.is_authenticated)
    return ActionLog.objects.create(
        user=user if authenticated else None,
        username=user.get_username() if authenticated else "",
        action=action,
        method=request.method,
        path=request.path[:512],
        status_code=status_code,
        ip=client_ip(request),
        object_repr=str(obj)[:255] if obj is not None else "",
        payload=payload or {},
    )
