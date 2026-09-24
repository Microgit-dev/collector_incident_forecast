from rest_framework import serializers, viewsets

from ..models import ActionLog


class ActionLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActionLog
        fields = (
            "id",
            "ts",
            "username",
            "action",
            "method",
            "path",
            "status_code",
            "ip",
            "object_repr",
            "object_type",
            "object_id",
            "payload",
        )


class ActionLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ActionLog.objects.all()
    serializer_class = ActionLogSerializer
    filterset_fields = ("action", "username", "method", "object_type", "object_id")
    search_fields = ("username", "path", "object_repr")
