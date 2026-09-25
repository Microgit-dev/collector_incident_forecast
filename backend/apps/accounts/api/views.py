from rest_framework import permissions, serializers, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Team, User
from ..roles import ROLES, Role
from ..selectors import teams_with_members


class TeamRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ("id", "code", "name", "kind")


class MeSerializer(serializers.ModelSerializer):
    roles = serializers.ListField(source="role_codes", child=serializers.CharField())
    permissions = serializers.SerializerMethodField()
    scope_node_name = serializers.CharField(source="scope_node.name", default=None)
    team = TeamRefSerializer(allow_null=True)
    command_chain = serializers.SerializerMethodField()
    contour = serializers.SerializerMethodField()

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
            "team",
            "command_chain",
            "roles",
            "permissions",
            "is_superuser",
            "contour",
        )

    def get_contour(self, obj: User) -> dict:
        """Контур, в котором работает пользователь, и адреса соседних — для перехода и плашки «Учебный»."""
        from django.conf import settings

        return {"code": settings.CONTOUR, "urls": settings.CONTOUR_URLS}

    def get_permissions(self, obj: User) -> list[str]:
        # Фронтенд прячет недоступные действия по этому списку; реальная проверка — на бэкенде
        return sorted(obj.get_all_permissions())

    def get_command_chain(self, obj: User) -> list[dict]:
        """Вышестоящие команды: кому уходит эскалация, если смена не отреагировала."""
        return TeamRefSerializer(obj.team.chain()[1:], many=True).data if obj.team else []


class MemberSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "username", "last_name", "first_name", "position", "phone", "roles")

    def get_roles(self, obj: User) -> list[dict]:
        codes = [g.name for g in obj.groups.all()]
        return [{"code": c, "title": ROLES[Role(c)].title} for c in codes if c in Role._value2member_map_]


class TeamSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display")
    scope_node_name = serializers.CharField(source="scope_node.name", default=None)
    lead = serializers.PrimaryKeyRelatedField(read_only=True)
    members = MemberSerializer(many=True)

    class Meta:
        model = Team
        fields = (
            "id",
            "code",
            "name",
            "kind",
            "kind_display",
            "scope_node",
            "scope_node_name",
            "parent",
            "lead",
            "members",
        )


class TeamViewSet(viewsets.ReadOnlyModelViewSet):
    """Оргструктура открыта всем сотрудникам: диспетчер должен видеть, кому передаётся инцидент."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TeamSerializer
    queryset = teams_with_members()
    pagination_class = None


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(MeSerializer(request.user).data)
