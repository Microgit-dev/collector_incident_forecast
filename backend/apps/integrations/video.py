"""
Проверка тревоги по камерам (ТЗ §12, шаг 4 «Верификация»: диспетчер при необходимости использует
камеры наблюдения). Камеры — в реестре assets.Camera (объект, пикет, ид в VMS); кадры берёт бэкенд
из системы видеонаблюдения (VideoClient) и отдаёт интерфейсу, поэтому браузеру не нужен доступ к VMS.

Ближайшие камеры: камеры объекта тревоги и его частей, а если их нет — объекта верхнего уровня;
порядок — по расстоянию в пикетах от места тревоги.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from apps.assets.models import Camera
from apps.topology.models import Node

from .clients import VideoClient, conf

LIMIT = 4


def enabled() -> bool:
    return conf("VMS_MODE") != "off"


def nearest(node: Node, picket: float | None = None, limit: int = LIMIT) -> list[Camera]:
    """Камеры у места тревоги: поддерево объекта, иначе ближайший предок с камерами."""
    cameras: list[Camera] = []
    current: Node | None = node
    while current is not None and not cameras:
        cameras = list(Camera.objects.filter(is_active=True, node__path__startswith=current.path))
        current = current.get_parent() if current.depth > 1 else None
    if picket is not None:
        cameras.sort(key=lambda c: abs(float(c.picket) - picket) if c.picket is not None else 1e9)
    return cameras[:limit]


def live_url(camera: Camera, at: datetime | None = None) -> str | None:
    template = conf("VMS_LIVE_URL")
    if not template or not enabled():
        return None
    return template.format(id=quote(camera.external_id), at=quote(at.isoformat()) if at else "")


def describe(camera: Camera, picket: float | None, at: datetime | None) -> dict:
    return {
        "id": camera.pk,
        "name": camera.name,
        "node": camera.node.name,
        "picket": float(camera.picket) if camera.picket is not None else None,
        "distance": round(abs(float(camera.picket) - picket), 1)
        if camera.picket is not None and picket is not None
        else None,
        "live_url": live_url(camera, at),
    }


def snapshot(camera: Camera, at: datetime | None = None) -> tuple[bytes, str]:
    """Кадр камеры на момент времени (архив VMS) или текущий. Результат обмена — на страницу «Интеграции»."""
    from .registry import mark

    try:
        content, content_type = VideoClient().snapshot(camera.external_id, at.isoformat() if at else None)
    except Exception as exc:
        mark("vms", False, error=f"{camera.external_id}: {exc}")
        raise
    mark("vms", True, {"camera": camera.external_id})
    return content, content_type
