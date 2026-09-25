from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.services import log_action
from apps.core.permissions import require_perm
from apps.incidents.models import Incident
from apps.topology.mixins import ScopedQuerySetMixin
from apps.topology.selectors import scope_queryset

from .. import services
from ..models import MaintenanceRecommendation, WorkOrder


class WorkOrderSerializer(serializers.ModelSerializer):
    node_name = serializers.CharField(source="node.name", read_only=True)
    assignee_name = serializers.CharField(source="assignee.get_full_name", default=None, read_only=True)

    class Meta:
        model = WorkOrder
        fields = (
            "id",
            "number",
            "status",
            "node",
            "node_name",
            "incident",
            "recommendation",
            "equipment",
            "work_type",
            "priority",
            "title",
            "description",
            "due_at",
            "assignee",
            "assignee_name",
            "external_id",
            "external_status",
            "external_assignee",
            "external_history",
            "external_synced_at",
            "report",
            "created_at",
        )
        read_only_fields = (
            "number",
            "status",
            "external_id",
            "external_status",
            "external_assignee",
            "external_history",
            "external_synced_at",
        )


class RecommendationSerializer(serializers.ModelSerializer):
    node_name = serializers.CharField(source="node.name", read_only=True)
    channel_name = serializers.CharField(source="channel.name", default=None, read_only=True)
    equipment_name = serializers.CharField(source="equipment.name", default=None, read_only=True)
    work_type_display = serializers.CharField(source="get_work_type_display", read_only=True)
    workorders = serializers.SerializerMethodField()

    def get_workorders(self, obj):
        return [{"id": w.pk, "number": w.number, "status": w.status} for w in obj.workorders.all()]

    class Meta:
        model = MaintenanceRecommendation
        fields = (
            "id",
            "node",
            "node_name",
            "channel_name",
            "equipment_name",
            "work_type_display",
            "workorders",
            "created_at",
            "equipment",
            "channel",
            "prediction",
            "work_type",
            "priority",
            "due_date",
            "rationale",
            "status",
        )


class WorkOrderViewSet(ScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = WorkOrder.objects.select_related("node", "assignee")
    serializer_class = WorkOrderSerializer
    filterset_fields = ("status", "work_type", "priority", "node", "assignee", "incident")
    search_fields = ("number", "title")
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        # Бригада видит только назначенные ей заявки
        if user.has_perm("workorders.execute_workorder") and not user.has_perm("workorders.add_workorder"):
            qs = qs.filter(assignee=user)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, number=services.next_number())

    @action(
        detail=False,
        methods=["post"],
        url_path="from-incident/(?P<incident_id>[0-9]+)",
        permission_classes=[require_perm("workorders.add_workorder")],
    )
    def from_incident(self, request, incident_id=None):
        incident = get_object_or_404(
            scope_queryset(Incident.objects.all(), request.user, "node"), pk=incident_id
        )
        from apps.incidents.services import IncidentError, claim

        try:
            # черновик заявки — тоже отклик: карточка достаётся тому, кто первым взялся
            incident = claim(incident, request.user, "Черновик заявки")
        except IncidentError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        order = services.draft_from_incident(incident, request.user)
        log_action(request, "workorder.draft", obj=order)
        return Response(WorkOrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], permission_classes=[require_perm("workorders.change_workorder")])
    def sync(self, request):
        """Забрать статусы из системы учёта заявок сейчас, не дожидаясь периодической задачи."""
        result = services.sync_external()
        log_action(request, "workorder.sync", payload=result)
        return Response(result)

    # Право проверяется внутри: оно зависит от целевого статуса (утвердить / исполнить / отменить)
    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def transition(self, request, pk=None):
        order = self.get_object()
        new_status = request.data.get("status")
        required = {
            WorkOrder.Status.APPROVED: "workorders.approve_workorder",
            WorkOrder.Status.IN_PROGRESS: "workorders.execute_workorder",
            WorkOrder.Status.DONE: "workorders.execute_workorder",
        }.get(new_status, "workorders.change_workorder")
        if not request.user.has_perm(required):
            return Response({"detail": "Недостаточно прав"}, status=status.HTTP_403_FORBIDDEN)
        try:
            services.transition(order, new_status, request.user)
        except (services.WorkOrderError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        log_action(request, "workorder.transition", obj=order, payload={"status": new_status})
        return Response(WorkOrderSerializer(order).data)


class RecommendationViewSet(ScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = MaintenanceRecommendation.objects.select_related(
        "node", "channel", "equipment"
    ).prefetch_related("workorders")
    serializer_class = RecommendationSerializer
    filterset_fields = ("status", "work_type", "priority", "node")
    ordering_fields = ("due_date", "priority", "created_at")
    http_method_names = ["get", "patch", "post", "head", "options"]

    def create(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @action(detail=True, methods=["post"], permission_classes=[require_perm("workorders.add_workorder")])
    def draft(self, request, pk=None):
        rec = self.get_object()
        order = services.draft_from_recommendation(rec, request.user)
        log_action(request, "workorder.draft", obj=order, payload={"recommendation": rec.pk})
        return Response(WorkOrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], permission_classes=[require_perm("workorders.add_workorder")])
    def generate(self, request):
        from ..recommendations import generate

        result = generate()
        log_action(request, "workorder.recommendations", payload=result)
        return Response(result)
