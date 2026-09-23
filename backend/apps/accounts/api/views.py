from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import User


class MeSerializer(serializers.ModelSerializer):
    roles = serializers.ListField(source="role_codes", child=serializers.CharField())
    permissions = serializers.SerializerMethodField()
    scope_node_name = serializers.CharField(source="scope_node.name", default=None)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "position",
            "scope_node",
            "scope_node_name",
            "roles",
            "permissions",
            "is_superuser",
        )

    def get_permissions(self, obj: User) -> list[str]:
        # Фронтенд прячет недоступные действия по этому списку; реальная проверка — на бэкенде
        return sorted(obj.get_all_permissions())


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(MeSerializer(request.user).data)
