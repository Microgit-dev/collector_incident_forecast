from rest_framework import mixins, serializers, viewsets

from apps.topology.mixins import ScopedQuerySetMixin

from ..models import ChannelDaily, ChannelState, Reading


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


class ChannelDailySerializer(serializers.ModelSerializer):
    class Meta:
        model = ChannelDaily
        fields = (
            "day",
            "channel",
            "readings",
            "normal",
            "warnings",
            "alarms",
            "faults",
            "power_losses",
            "unknowns",
            "events",
            "invalid",
            "numeric_avg",
            "numeric_min",
            "numeric_max",
            "first_ts",
            "last_ts",
        )


class ChannelDailyViewSet(ScopedQuerySetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Суточная история канала за все годы (витрина из архива) — для графиков и сезонности."""

    queryset = ChannelDaily.objects.order_by("-day")
    serializer_class = ChannelDailySerializer
    scope_field = "channel__node"
    filterset_fields = {"channel": ["exact"], "day": ["gte", "lte"]}
    ordering_fields = ("day",)
