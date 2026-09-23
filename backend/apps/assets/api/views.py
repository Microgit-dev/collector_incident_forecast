from rest_framework import serializers, viewsets

from apps.topology.mixins import ScopedQuerySetMixin

from ..models import Channel, Equipment, SensorType


class SensorTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SensorType
        fields = ("id", "name", "system_type", "domain", "profile")


class ChannelSerializer(serializers.ModelSerializer):
    sensor_type_name = serializers.CharField(source="sensor_type.name", default=None, read_only=True)
    node_name = serializers.CharField(source="node.name", read_only=True)

    class Meta:
        model = Channel
        fields = (
            "id",
            "external_id",
            "name",
            "tag",
            "node",
            "node_name",
            "sensor_type",
            "sensor_type_name",
            "profile_override",
            "picket",
            "location_hint",
            "is_active",
            "in_catalog",
        )


class EquipmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Equipment
        fields = (
            "id",
            "kind",
            "node",
            "name",
            "inventory_number",
            "picket",
            "channels",
            "commissioned_at",
            "last_maintenance_at",
            "maintenance_interval_days",
            "mtbf_hours",
            "source",
        )


class SensorTypeViewSet(viewsets.ModelViewSet):
    queryset = SensorType.objects.all()
    serializer_class = SensorTypeSerializer
    filterset_fields = ("domain", "system_type")


class ChannelViewSet(ScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = Channel.objects.select_related("sensor_type", "node")
    serializer_class = ChannelSerializer
    filterset_fields = ("node", "sensor_type", "sensor_type__domain", "is_active", "in_catalog")
    search_fields = ("name", "tag", "=external_id")


class EquipmentViewSet(ScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = Equipment.objects.select_related("node").prefetch_related("channels")
    serializer_class = EquipmentSerializer
    filterset_fields = ("kind", "node", "source")
    search_fields = ("name", "inventory_number")
