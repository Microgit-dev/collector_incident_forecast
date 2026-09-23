from rest_framework import serializers

from ..models import Node


class NodeSerializer(serializers.ModelSerializer):
    # Родитель вычисляется из materialized path без лишних запросов к БД
    parent_path = serializers.SerializerMethodField()

    class Meta:
        model = Node
        fields = (
            "id",
            "external_id",
            "kind",
            "name",
            "depth",
            "path",
            "parent_path",
            "picket_from",
            "picket_to",
            "geometry",
            "is_active",
        )

    def get_parent_path(self, obj: Node) -> str | None:
        return obj.path[: -Node.steplen] or None
