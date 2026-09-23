from django.utils import timezone
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ("id", "created_at", "title", "body", "level", "link", "payload", "read_at")


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Свои уведомления видит любой вошедший пользователь — отдельное право не нужно."""

    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = {"read_at": ["isnull"], "level": ["exact"]}

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=False)
    def unread_count(self, request):
        return Response({"count": self.get_queryset().filter(read_at=None).count()})

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        self.get_queryset().filter(pk=pk, read_at=None).update(read_at=timezone.now())
        return Response(status=204)

    @action(detail=False, methods=["post"])
    def read_all(self, request):
        updated = self.get_queryset().filter(read_at=None).update(read_at=timezone.now())
        return Response({"updated": updated})
