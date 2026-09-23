from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from ..selectors import overview


class OverviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(overview(request.user))
