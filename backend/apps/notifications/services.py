"""
Доставка уведомлений: запись в БД (история, непрочитанные) + push по WebSocket.
Новые каналы (email, Telegram, мобильный push) добавляются как ещё один Transport.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import Notification

logger = logging.getLogger(__name__)


def user_group(user_id: int) -> str:
    return f"user.{user_id}"


def notify(
    users: Iterable,
    *,
    title: str,
    body: str = "",
    level: str = "medium",
    link: str = "",
    payload: dict | None = None,
) -> int:
    items = Notification.objects.bulk_create(
        [
            Notification(user=u, title=title[:255], body=body, level=level, link=link, payload=payload or {})
            for u in users
        ]
    )
    layer = get_channel_layer()
    if layer is None:
        return len(items)
    for n in items:
        message = {
            "type": "notification.push",
            "notification": {
                "id": n.pk,
                "title": n.title,
                "body": n.body,
                "level": n.level,
                "link": n.link,
                "payload": n.payload,
                "created_at": n.created_at.isoformat(),
            },
        }
        try:
            async_to_sync(layer.group_send)(user_group(n.user_id), message)
        except Exception:  # недоступность Redis не должна ронять бизнес-операцию
            logger.exception("websocket push failed")
    return len(items)


def broadcast(users: Iterable, event: dict) -> None:
    """Событие без записи в уведомления: интерфейсу — обновить очередь и карточку (например, её взяли)."""
    layer = get_channel_layer()
    if layer is None:
        return
    for user in users:
        try:
            async_to_sync(layer.group_send)(user_group(user.pk), {"type": "incident.update", "event": event})
        except Exception:  # недоступность Redis не должна ронять бизнес-операцию
            logger.exception("websocket broadcast failed")
