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
