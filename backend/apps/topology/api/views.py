from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from ..mixins import ScopedQuerySetMixin
from ..models import Node
from .serializers import NodeSerializer


class NodeViewSet(ScopedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Node.objects.order_by("path")
    serializer_class = NodeSerializer
    scope_field = ""
    filterset_fields = ("kind", "depth", "is_active")
    search_fields = ("name",)

    @action(detail=False, url_path="geojson")
    def geojson(self, request):
        """Схематическая карта: FeatureCollection узлов, у которых задана геометрия."""
        features = [
            {
                "type": "Feature",
                "id": node.pk,
                "geometry": node.geometry,
                "properties": {"name": node.name, "kind": node.kind, "depth": node.depth},
            }
            for node in self.get_queryset().exclude(geometry=None)
        ]
        return Response({"type": "FeatureCollection", "features": features})
