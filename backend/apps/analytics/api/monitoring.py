from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import log_action
from apps.topology.models import Node, NodeKind

from .. import monitoring
from ..cache import cached


class MonitoringView(APIView):
    """Карта мониторинга роли: зоны, объекты, карточки, заявки, сводка; кеш 30 с на пользователя."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        data = cached(
            "monitoring",
            request.user,
            (request.user.pk,),
            lambda: monitoring.monitoring_map(request.user),
            ttl=30,
        )
        return Response({**data, "map": {"light": settings.MAP_STYLE_LIGHT, "dark": settings.MAP_STYLE_DARK}})


class MonitoringOthersView(APIView):
    """Объекты вне зоны ответственности — постранично (по 10), смежные зоны первыми."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            page = int(request.query_params.get("page", 1))
        except ValueError:
            page = 1
        return Response(
            monitoring.others(request.user, page=page, q=request.query_params.get("q", "").strip())
        )


class MonitoringObjectView(APIView):
    """Объект на карте: в своей зоне — датчики, карточки и заявки; вне зоны — только название и зона."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk: int):
        obj = get_object_or_404(Node, pk=pk, kind=NodeKind.COMPLEX)
        data = monitoring.object_detail(request.user, obj)
        if data["mine"]:
            log_action(request, "monitoring.object.view", obj=obj)
        return Response(data)
