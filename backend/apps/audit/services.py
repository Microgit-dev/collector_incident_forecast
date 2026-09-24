from datetime import timedelta

from django.utils import timezone

from .models import ActionLog

# Повторное открытие той же карточки тем же пользователем в пределах окна — один просмотр:
# интерфейс перезапрашивает карточку при каждом обновлении, журнал не должен зашумляться.
VIEW_DEDUP = timedelta(minutes=10)


def client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _ref(obj) -> dict:
    if obj is None:
        return {"object_repr": "", "object_type": "", "object_id": ""}
    meta = getattr(obj, "_meta", None)
    return {
        "object_repr": str(obj)[:255],
        "object_type": meta.label_lower if meta else "",
        "object_id": str(obj.pk) if meta else "",
    }


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
        payload=payload or {},
        **_ref(obj),
    )


def log_view(request, obj, action: str) -> bool:
    """Просмотр карточки (ТЗ §11: кто открыл инцидент или прогноз). True — если записан новый просмотр."""
    ref = _ref(obj)
    recent = ActionLog.objects.filter(
        user=request.user,
        action=action,
        object_type=ref["object_type"],
        object_id=ref["object_id"],
        ts__gte=timezone.now() - VIEW_DEDUP,
    )
    if recent.exists():
        return False
    log_action(request, action, obj=obj, status_code=200)
    return True
