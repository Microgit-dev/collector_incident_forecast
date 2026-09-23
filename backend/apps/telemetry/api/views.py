from rest_framework import mixins, serializers, viewsets

from apps.topology.mixins import ScopedQuerySetMixin

from ..models import ChannelState, Reading


class ReadingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reading
        fields = (
            "ts",
            "event_id",
            "channel",
            "raw_value",
            "raw_alarm",
            "numeric",
            "state",
            "facet",
            "quality",
        )


class ChannelStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChannelState
        fields = ("id", "channel", "facet", "state", "numeric", "raw_value", "changed_at", "last_seen_at")


class ReadingViewSet(ScopedQuerySetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    История показаний; фильтровать по каналу и периоду (ts__gte/ts__lt).
    Только список: у hypertable составной ключ, detail-маршрут не нужен.
    """

    queryset = Reading.objects.order_by("-ts")
    serializer_class = ReadingSerializer
    scope_field = "channel__node"
    filterset_fields = {"channel": ["exact"], "state": ["exact"], "facet": ["exact"], "ts": ["gte", "lt"]}
    ordering_fields = ("ts",)


class ChannelStateViewSet(ScopedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = ChannelState.objects.select_related("channel")
    serializer_class = ChannelStateSerializer
    scope_field = "channel__node"
    filterset_fields = ("state", "facet", "channel", "channel__node")
