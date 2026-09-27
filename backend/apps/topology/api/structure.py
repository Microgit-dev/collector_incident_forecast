from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Secondment, User
from apps.analytics.workspace import roles_of
from apps.assets.models import Channel, SensorType
from apps.audit.services import log_action

from .. import geo, structure
from ..models import Node, NodeKind
from ..selectors import has_global_scope, in_scope, objects_under, zone_of


def _err(exc: Exception, status: int = 400) -> Response:
    return Response({"detail": str(exc)}, status=status)


def _zone(z: Node) -> dict:
    return {
        "id": z.pk,
        "name": z.name,
        "color": z.color,
        "geometry": z.geometry,
        "center": geo.centroid(z.geometry),
        "adjacent": list(z.adjacent.values_list("pk", flat=True)),
        "objects": objects_under(z).count(),
        "staff": z.users.filter(is_active=True).count(),
    }


def _object(o: Node) -> dict:
    zone = zone_of(o)
    return {
        "id": o.pk,
        "name": o.name,
        "zone": zone.pk if zone else None,
        "criticality": o.criticality,
        "geometry": o.geometry,
        "source": o.geometry_source,
        "center": geo.centroid(o.geometry),
        "channels": o.channels.count()
        + Channel.objects.filter(node__path__startswith=o.path).exclude(node=o).count(),
    }


def _person(u: User) -> dict:
    zone = zone_of(u.scope_node) if u.scope_node_id else None
    return {
        "id": u.pk,
        "name": u.get_full_name() or u.username,
        "roles": roles_of(u),
        "scope": u.scope_node_id,
        "scope_name": u.scope_node.name if u.scope_node_id else "Все объекты",
        "zone": zone.pk if zone else None,
        "team": u.team.name if u.team_id else None,
    }


def _secondment(s: Secondment) -> dict:
    return {
        "id": s.pk,
        "user": s.user_id,
        "user_name": s.user.get_full_name() or s.user.username,
        "zone": s.zone_id,
        "zone_name": s.zone.name,
        "ends_at": s.ends_at,
        "reason": s.reason,
        "emergency": s.emergency,
        "by": (s.created_by.get_full_name() or s.created_by.username) if s.created_by else None,
    }


class StructureView(APIView):
    """Всё для редактора структуры: зоны, объекты, типы датчиков, сотрудники и командирования, права."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        # вкладка открыта, если можно править; «новый объект / датчик» — только тем, кто их заводит
        # (кто за что отвечает — accounts/operations.py)
        can = {
            "zones": user.has_perm("topology.manage_zones"),
            "objects": user.has_perm("topology.add_node") or user.has_perm("topology.change_node"),
            "add_objects": user.has_perm("topology.add_node"),
            "sensors": user.has_perm("assets.add_channel") or user.has_perm("assets.change_channel"),
            "add_sensors": user.has_perm("assets.add_channel"),
            "staff": user.has_perm("accounts.assign_staff"),
        }
        if not any(can.values()):
            return Response({"detail": "Недостаточно прав"}, status=403)
        scope = None if has_global_scope(user) else user.scope_node
        zones = structure.zones_for(user)
        objects = (
            objects_under(scope).order_by("name") if scope or has_global_scope(user) else Node.objects.none()
        )
        district = structure.district_for(user)
        return Response(
            {
                "can": can,
                "district": {"id": district.pk, "name": district.name},
                "zones": [_zone(z) for z in zones],
                "objects": [_object(o) for o in objects],
                "sensor_types": list(
                    SensorType.objects.order_by("system_type", "name").values("id", "name", "system_type")
                ),
                "staff": [_person(u) for u in structure.staff_for(user).order_by("last_name", "username")]
                if can["staff"]
                else [],
                "secondments": [_secondment(s) for s in structure.active_secondments(user)]
                if can["staff"]
                else [],
                "overpass": bool(settings.OVERPASS_URL),
                "map": {"light": settings.MAP_STYLE_LIGHT, "dark": settings.MAP_STYLE_DARK},
            }
        )


class ZonesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            zone = structure.create_zone(
                request.user,
                name=request.data.get("name", ""),
                geometry=request.data.get("geometry"),
                color=request.data.get("color", ""),
            )
        except (structure.StructureError, geo.GeoError) as exc:
            return _err(exc)
        log_action(request, "structure.zone.create", obj=zone)
        return Response(_zone(zone), status=201)


class ZoneDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk: int):
        zone = get_object_or_404(Node, pk=pk, kind=NodeKind.ZONE)
        try:
            zone = structure.update_zone(request.user, zone, request.data)
        except (structure.StructureError, geo.GeoError, ValueError) as exc:
            return _err(exc)
        log_action(request, "structure.zone.update", obj=zone, payload={"fields": sorted(request.data)})
        return Response(_zone(zone))

    def get(self, request, pk: int):
        """Подсказка смежности: зоны, чьи контуры касаются или ближе 150 м."""
        zone = get_object_or_404(Node, pk=pk, kind=NodeKind.ZONE)
        return Response({"suggested": [z.pk for z in structure.suggest_adjacent(zone)]})


class ObjectsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            obj = structure.create_object(
                request.user,
                parent_id=request.data.get("zone"),
                name=request.data.get("name", ""),
                geometry=request.data.get("geometry"),
                criticality=request.data.get("criticality", 3),
                source=request.data.get("source", ""),
            )
        except (structure.StructureError, geo.GeoError, ValueError, TypeError) as exc:
            return _err(exc)
        log_action(request, "structure.object.create", obj=obj, payload={"source": obj.geometry_source})
        return Response({**_object(obj), "warning": getattr(obj, "warning", "")}, status=201)


class ObjectDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk: int):
        obj = get_object_or_404(Node, pk=pk, kind=NodeKind.COMPLEX)
        try:
            obj = structure.update_object(request.user, obj, request.data)
        except (structure.StructureError, geo.GeoError, ValueError, TypeError) as exc:
            return _err(exc)
        log_action(request, "structure.object.update", obj=obj, payload={"fields": sorted(request.data)})
        return Response(_object(obj))

    def get(self, request, pk: int):
        """Датчики объекта (и его частей) для редактора."""
        obj = get_object_or_404(Node, pk=pk)
        if not in_scope(request.user, obj):
            return Response({"detail": "Вне вашей зоны"}, status=404)
        rows = Channel.objects.filter(node__path__startswith=obj.path).select_related("sensor_type", "node")
        return Response(
            [
                {
                    "id": c.pk,
                    "external_id": c.external_id,
                    "name": c.name,
                    "type": c.sensor_type.name if c.sensor_type else "",
                    "node": c.node_id,
                    "node_name": c.node.name,
                    "picket": float(c.picket) if c.picket is not None else None,
                    "location": c.location,
                    "manual": not c.in_catalog,
                }
                for c in rows.order_by("node__path", "name")[:3000]
            ]
        )


class SensorsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            channel = structure.create_sensor(
                request.user,
                node_id=request.data.get("node"),
                name=request.data.get("name", ""),
                sensor_type_id=request.data.get("sensor_type"),
                picket=request.data.get("picket"),
                location=request.data.get("location"),
            )
        except (structure.StructureError, ValueError) as exc:
            return _err(exc)
        log_action(request, "structure.sensor.create", obj=channel)
        return Response(
            {"id": channel.pk, "external_id": channel.external_id, "name": channel.name}, status=201
        )


class SensorDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk: int):
        channel = get_object_or_404(Channel.objects.select_related("node"), pk=pk)
        try:
            channel = structure.attach_sensor(
                request.user,
                channel,
                node_id=request.data.get("node"),
                location=request.data.get("location") if "location" in request.data else None,
            )
        except structure.StructureError as exc:
            return _err(exc)
        log_action(request, "structure.sensor.update", obj=channel, payload={"fields": sorted(request.data)})
        return Response({"id": channel.pk, "node": channel.node_id, "location": channel.location})


class DetectBuildingView(APIView):
    """Автовыделение здания под точкой щелчка — предложение контура, которое можно поправить перед сохранением."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.has_perm("topology.add_node") and not request.user.has_perm(
            "topology.manage_zones"
        ):
            return Response({"detail": "Недостаточно прав"}, status=403)
        try:
            lon, lat = float(request.query_params["lon"]), float(request.query_params["lat"])
        except (KeyError, ValueError):
            return Response({"detail": "Нужны lon и lat"}, status=400)
        try:
            return Response(geo.detect_building(lon, lat))
        except geo.GeoError as exc:
            return _err(exc, 404 if "не найдено" in str(exc) else 503)


class StaffActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int, action: str):
        employee = get_object_or_404(User, pk=pk)
        try:
            if action == "assign":
                structure.assign(request.user, employee, request.data.get("node"))
                log_action(
                    request,
                    "structure.staff.assign",
                    obj=employee,
                    payload={"node": request.data.get("node")},
                )
                return Response(_person(User.objects.select_related("scope_node", "team").get(pk=pk)))
            if action == "second":
                record = structure.second(
                    request.user,
                    employee,
                    zone_id=request.data.get("zone"),
                    hours=request.data.get("hours", 8),
                    reason=request.data.get("reason", ""),
                    emergency=bool(request.data.get("emergency")),
                )
                log_action(
                    request,
                    "structure.staff.second",
                    obj=employee,
                    payload={"zone": record.zone_id, "emergency": record.emergency},
                )
                return Response(_secondment(record), status=201)
        except (structure.StructureError, ValueError, TypeError) as exc:
            return _err(exc)
        return Response({"detail": "Неизвестное действие"}, status=404)


class SecondmentRecallView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int):
        record = get_object_or_404(Secondment.objects.select_related("zone", "user"), pk=pk)
        try:
            structure.recall(request.user, record)
        except structure.StructureError as exc:
            return _err(exc)
        log_action(request, "structure.staff.recall", obj=record.user)
        return Response(_secondment(record))
