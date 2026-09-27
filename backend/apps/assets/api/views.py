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
    node_name = serializers.CharField(source="node.name", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    condition_display = serializers.CharField(source="get_condition_display", read_only=True)
    next_maintenance_at = serializers.DateField(read_only=True)

    class Meta:
        model = Equipment
        fields = (
            "id",
            "kind",
            "kind_display",
            "node",
            "node_name",
            "name",
            "inventory_number",
            "picket",
            "channels",
            "commissioned_at",
            "last_maintenance_at",
            "maintenance_interval_days",
            "next_maintenance_at",
            "mtbf_hours",
            "source",
            "condition",
            "condition_display",
            "condition_at",
            "is_active",
            "synced_at",
        )
        # состояние меняется только осмотром (история в EquipmentInspection), источник — синхронизацией
        read_only_fields = ("source", "condition", "condition_at", "synced_at")


class SensorTypeViewSet(viewsets.ModelViewSet):
    queryset = SensorType.objects.all()
    serializer_class = SensorTypeSerializer
    filterset_fields = ("domain", "system_type")


class ChannelViewSet(ScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = Channel.objects.select_related("sensor_type", "node")
    serializer_class = ChannelSerializer
    filterset_fields = ("node", "sensor_type", "sensor_type__domain", "is_active", "in_catalog")
    search_fields = ("name", "tag", "=external_id")

    def get_queryset(self):
        qs = super().get_queryset()
        # ?within=<узел> — каналы всего поддерева (у комплекса каналы лежат во вложенных объектах)
        if within := self.request.query_params.get("within"):
            from apps.topology.models import Node

            node = Node.objects.filter(pk=within).first()
            qs = qs.filter(node__path__startswith=node.path) if node else qs.none()
        return qs


class EquipmentViewSet(ScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = (
        Equipment.objects.select_related("node").prefetch_related("channels").order_by("node__path", "name")
    )
    serializer_class = EquipmentSerializer
    filterset_fields = ("kind", "node", "source", "condition", "is_active")
    search_fields = ("name", "inventory_number")
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        if within := self.request.query_params.get("within"):
            from apps.topology.models import Node

            node = Node.objects.filter(pk=within).first()
            qs = qs.filter(node__path__startswith=node.path) if node else qs.none()
        return qs

    def perform_create(self, serializer):
        from apps.topology.selectors import in_scope

        if not in_scope(self.request.user, serializer.validated_data["node"]):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Объект вне вашей зоны ответственности")
        # заведённая вручную единица не перезаписывается синхронизацией с реестром заказчика
        serializer.save(source="manual")
