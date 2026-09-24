from django.db.models import Count, Max, Min

from .models import ActionLog


def viewers(obj, action: str) -> list[dict]:
    """Кто и когда открывал карточку: первый и последний просмотр, число просмотров."""
    rows = (
        ActionLog.objects.filter(action=action, object_type=obj._meta.label_lower, object_id=str(obj.pk))
        .exclude(user=None)
        .values("user", "user__username", "user__last_name", "user__first_name", "user__position")
        .annotate(first=Min("ts"), last=Max("ts"), times=Count("id"))
        .order_by("first")
    )
    return [
        {
            "user": r["user"],
            "username": r["user__username"],
            "name": " ".join(filter(None, [r["user__last_name"], r["user__first_name"]]))
            or r["user__username"],
            "position": r["user__position"],
            "first_viewed_at": r["first"],
            "last_viewed_at": r["last"],
            "times": r["times"],
        }
        for r in rows
    ]
