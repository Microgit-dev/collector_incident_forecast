from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from ..flood import flood_reduction
from ..selectors import overview


class OverviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(overview(request.user))


class FloodView(APIView):
    """Снижение нагрузки: сигналы потока → эпизоды за период до «времени данных»."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from apps.forecasting.data import data_clock

        end = data_clock()
        if end is None:
            return Response({"signals": 0, "episodes": 0, "factor": None})
        days = min(max(int(request.query_params.get("days", 30)), 1), 30)
        return Response(flood_reduction(end, days))


class ReplayView(APIView):
    """Разбор исторического эпизода: объект и интервал до 24 часов."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from datetime import datetime

        from django.shortcuts import get_object_or_404

        from apps.audit.services import log_action
        from apps.topology.models import Node
        from apps.topology.selectors import scope_queryset

        from ..replay import ReplayError, replay

        node = get_object_or_404(
            scope_queryset(Node.objects.all(), request.user, ""), pk=request.query_params.get("node")
        )
        try:
            start = datetime.fromisoformat(request.query_params["from"])
            end = datetime.fromisoformat(request.query_params["to"])
            result = replay(node, start, end)
        except (KeyError, ValueError) as exc:
            return Response({"detail": f"Неверные параметры: {exc}"}, status=400)
        except ReplayError as exc:
            return Response({"detail": str(exc)}, status=400)
        log_action(
            request, "analytics.replay", obj=node, payload={"from": start.isoformat(), "to": end.isoformat()}
        )
        return Response(result)
