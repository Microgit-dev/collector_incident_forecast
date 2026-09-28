from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assets.models import Equipment, EquipmentCondition
from apps.audit.services import log_action
from apps.core.permissions import require_perm
from apps.forecasting.models import RiskLevel
from apps.incidents.models import Incident
from apps.topology.mixins import ScopedQuerySetMixin
from apps.topology.selectors import scope_queryset

from .. import maintenance, services
from ..models import (
    EquipmentInspection,
    MaintenanceNorm,
    MaintenanceRecommendation,
    MaintenanceSchedule,
    ScheduleLine,
    WorkOrder,
    WorkType,
)


class WorkOrderSerializer(serializers.ModelSerializer):
    node_name = serializers.CharField(source="node.name", read_only=True)
    assignee_name = serializers.CharField(source="assignee.get_full_name", default=None, read_only=True)
    equipment_name = serializers.CharField(source="equipment.name", default=None, read_only=True)

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
            "equipment_name",
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
    queryset = WorkOrder.objects.select_related("node", "assignee", "equipment")
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
            if new_status == WorkOrder.Status.DONE:
                # выполнение: отчёт бригады и фактическое состояние оборудования (в реестр)
                if order.status != WorkOrder.Status.IN_PROGRESS:
                    raise services.WorkOrderError("Выполненной можно отметить только заявку в работе")
                condition = request.data.get("condition") or ""
                if condition and condition not in EquipmentCondition.values:
                    raise services.WorkOrderError("Неизвестное состояние оборудования")
                maintenance.complete(
                    order,
                    request.user,
                    report=str(request.data.get("report") or "")[:4000],
                    condition=condition,
                    notes=str(request.data.get("notes") or "")[:4000],
                )
            else:
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


class InspectionSerializer(serializers.ModelSerializer):
    inspector_name = serializers.CharField(source="inspector.get_full_name", default=None, read_only=True)
    condition_display = serializers.CharField(source="get_condition_display", read_only=True)
    workorder_number = serializers.CharField(source="workorder.number", default=None, read_only=True)

    class Meta:
        model = EquipmentInspection
        fields = (
            "id",
            "equipment",
            "inspected_at",
            "inspector",
            "inspector_name",
            "condition",
            "condition_display",
            "maintenance",
            "notes",
            "workorder",
            "workorder_number",
        )
        read_only_fields = ("inspected_at", "inspector", "workorder")


class InspectionViewSet(ScopedQuerySetMixin, viewsets.ModelViewSet):
    """Осмотры и ТО оборудования: фактическое состояние (инженер ТО при обходе, бригада — по заявке)."""

    queryset = EquipmentInspection.objects.select_related("inspector", "workorder")
    serializer_class = InspectionSerializer
    scope_field = "equipment__node"
    filterset_fields = ("equipment", "condition", "workorder")
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        equipment = get_object_or_404(
            scope_queryset(Equipment.objects.all(), request.user, "node"),
            pk=serializer.validated_data["equipment"].pk,
        )
        inspection = maintenance.inspect(
            equipment,
            request.user,
            serializer.validated_data["condition"],
            serializer.validated_data.get("notes", ""),
            maintenance=serializer.validated_data.get("maintenance", False),
        )
        log_action(
            request, "equipment.inspection", obj=equipment, payload={"condition": inspection.condition}
        )
        return Response(self.get_serializer(inspection).data, status=status.HTTP_201_CREATED)


class MaintenancePlanView(APIView):
    """План ТО зоны (инженер ТО, руководитель); ?format=xlsx — выгрузка."""

    permission_classes = [require_perm("workorders.plan_maintenance")]

    def get(self, request):
        try:
            horizon = min(365, max(7, int(request.query_params.get("horizon", maintenance.HORIZON_DAYS))))
        except ValueError:
            horizon = maintenance.HORIZON_DAYS
        data = maintenance.plan(request.user, horizon)
        from ..schedules import due_lines

        data["schedule_due"] = due_lines(request.user)
        data["kpis"]["schedule_unplanned"] = sum(1 for r in data["schedule_due"] if not r["planned"])
        if request.query_params.get("export") == "xlsx":
            from django.http import HttpResponse

            response = HttpResponse(
                maintenance.export_xlsx(data),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = (
                f'attachment; filename="maintenance_plan_{data["today"]:%Y%m%d}.xlsx"'
            )
            log_action(request, "maintenance.export", payload={"horizon": horizon})
            return response
        return Response(data)


class ScheduleSerializer(serializers.Serializer):
    equipment = serializers.IntegerField(required=False)
    recommendation = serializers.IntegerField(required=False)
    schedule_line = serializers.IntegerField(required=False)
    date = serializers.DateField()
    work_type = serializers.ChoiceField(choices=WorkType.choices, required=False)
    priority = serializers.ChoiceField(choices=RiskLevel.choices, required=False, default="medium")

    def validate(self, attrs):
        if sum(bool(attrs.get(k)) for k in ("equipment", "recommendation", "schedule_line")) != 1:
            raise serializers.ValidationError("Укажите оборудование, рекомендацию или строку графика")
        return attrs


class MaintenanceScheduleView(APIView):
    """Поставить работу в план на дату: черновик заявки, дальше — утверждение руководителем."""

    permission_classes = [require_perm("workorders.plan_maintenance")]

    def post(self, request):
        if not request.user.has_perm("workorders.add_workorder"):
            return Response({"detail": "Недостаточно прав"}, status=status.HTTP_403_FORBIDDEN)
        serializer = ScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("equipment"):
            eq = get_object_or_404(
                scope_queryset(Equipment.objects.select_related("node"), request.user, "node"),
                pk=data["equipment"],
            )
            order = maintenance.schedule_equipment(
                eq, data["date"], request.user, data.get("work_type"), data["priority"]
            )
        elif data.get("schedule_line"):
            from ..models import ScheduleLine
            from ..schedules import schedule_line

            line = get_object_or_404(
                scope_queryset(ScheduleLine.objects.select_related("schedule"), request.user, "node"),
                pk=data["schedule_line"],
                schedule__status="approved",
            )
            order = schedule_line(line, data["date"], request.user)
        else:
            rec = get_object_or_404(
                scope_queryset(
                    MaintenanceRecommendation.objects.select_related("node"), request.user, "node"
                ),
                pk=data["recommendation"],
            )
            order = maintenance.schedule_recommendation(rec, data["date"], request.user)
        log_action(request, "maintenance.schedule", obj=order)
        return Response(WorkOrderSerializer(order).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------- регламент и графики ТО / ППР

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class NormSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaintenanceNorm
        fields = ("id", "type_name", "system", "unit", "visits_per_year", "repairs_per_year", "ppr", "source")
        read_only_fields = ("source",)


class NormViewSet(viewsets.ModelViewSet):
    """Регламент ТО по видам оборудования: видят все с планом ТО, правит инженер ТО и руководитель."""

    queryset = MaintenanceNorm.objects.all()
    serializer_class = NormSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [require_perm("workorders.view_maintenancenorm")()]
        return [require_perm("workorders.plan_maintenance")()]

    def perform_update(self, serializer):
        norm = serializer.save(source="правка инженера ТО")
        log_action(self.request, "maintenance.norm", obj=norm)

    def perform_create(self, serializer):
        norm = serializer.save(source="правка инженера ТО")
        log_action(self.request, "maintenance.norm", obj=norm)


class ScheduleLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleLine
        fields = (
            "id",
            "order",
            "node",
            "object_label",
            "type_name",
            "quantity",
            "unit",
            "months",
            "month",
            "batch",
            "dismantle_on",
            "delivery_on",
            "pickup_on",
            "acceptance_on",
            "note",
        )


class MaintenanceScheduleSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    created_by_name = serializers.CharField(source="created_by.get_full_name", default=None, read_only=True)
    approved_by_name = serializers.CharField(source="approved_by.get_full_name", default=None, read_only=True)
    zone_name = serializers.CharField(source="zone.name", default=None, read_only=True)

    class Meta:
        model = MaintenanceSchedule
        fields = (
            "id",
            "kind",
            "kind_display",
            "year",
            "title",
            "source",
            "source_display",
            "status",
            "status_display",
            "zone",
            "zone_name",
            "created_by_name",
            "approved_by_name",
            "file_name",
            "stats",
            "created_at",
        )


class MaintenanceScheduleViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Графики ТО и ТР и план-графики ППР в формах заказчика: сформировать по реестру зоны, загрузить
    файл заказчика, выгрузить XLSX, сверить генератор с графиком заказчика, утвердить.
    """

    serializer_class = MaintenanceScheduleSerializer
    filterset_fields = ("kind", "year", "source", "status")
    parser_classes = [JSONParser, MultiPartParser]

    def get_permissions(self):
        return [require_perm("workorders.plan_maintenance")()]

    def get_queryset(self):
        from django.db.models import Q

        from apps.topology.selectors import has_global_scope, scope_paths

        qs = MaintenanceSchedule.objects.select_related("zone", "created_by", "approved_by")
        user = self.request.user
        if has_global_scope(user):
            return qs
        condition = Q(zone__isnull=True)
        for path in scope_paths(user):
            condition |= Q(zone__path__startswith=path)
        return qs.filter(condition)

    def retrieve(self, request, *args, **kwargs):
        schedule = self.get_object()
        data = self.get_serializer(schedule).data
        data["lines"] = ScheduleLineSerializer(schedule.lines.all(), many=True).data
        return Response(data)

    @action(detail=False, methods=["post"])
    def generate(self, request):
        from .. import schedules

        kind = request.data.get("kind")
        if kind not in MaintenanceSchedule.Kind.values:
            return Response({"detail": "Вид графика: to_tr или ppr"}, status=400)
        year = int(request.data.get("year") or timezone.localdate().year)
        schedule = schedules.generate(kind, year, request.user)
        if not schedule.lines.exists():
            schedule.delete()
            return Response({"detail": "В зоне нет оборудования с видом по регламенту"}, status=409)
        log_action(request, "maintenance.schedule_generate", obj=schedule)
        return Response(self.get_serializer(schedule).data, status=201)

    @action(detail=False, methods=["post"], url_path="import")
    def import_file(self, request):
        from .. import schedules

        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "Приложите файл графика (XLSX)"}, status=400)
        if upload.size > 20 * 2**20:
            return Response({"detail": "Файл больше 20 МБ"}, status=400)
        try:
            schedule = schedules.import_customer(upload.read(), upload.name, request.user)
        except (schedules.ScheduleFileError, ValueError, KeyError, OSError) as exc:
            return Response({"detail": f"Не удалось прочитать график: {exc}"}, status=400)
        schedules.validate(schedule)
        log_action(request, "maintenance.schedule_import", obj=schedule, payload={"file": upload.name})
        return Response(self.get_serializer(schedule).data, status=201)

    @action(detail=True, methods=["get"])
    def xlsx(self, request, pk=None):
        from django.http import HttpResponse

        from .. import schedules

        schedule = self.get_object()
        response = HttpResponse(schedules.export_xlsx(schedule), content_type=XLSX)
        name = "grafik_to_tr" if schedule.kind == "to_tr" else "plan_grafik_ppr"
        response["Content-Disposition"] = f'attachment; filename="{name}_{schedule.year}_{schedule.pk}.xlsx"'
        return response

    @action(detail=True, methods=["post"])
    def validate(self, request, pk=None):
        from .. import schedules

        return Response(schedules.validate(self.get_object()))

    @action(detail=True, methods=["post"], url_path="derive-norms")
    def derive_norms(self, request, pk=None):
        from .. import schedules

        schedule = self.get_object()
        if schedule.kind != MaintenanceSchedule.Kind.TO_TR:
            return Response({"detail": "Регламент выводится из графика ТО и ТР"}, status=400)
        result = schedules.derive_norms(schedule)
        log_action(request, "maintenance.derive_norms", obj=schedule, payload=result)
        return Response(result)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        if not request.user.has_perm("workorders.approve_workorder"):
            return Response({"detail": "Утверждает руководитель"}, status=403)
        schedule = self.get_object()
        schedule.status, schedule.approved_by = MaintenanceSchedule.Status.APPROVED, request.user
        schedule.save(update_fields=["status", "approved_by", "updated_at"])
        # в году один действующий график каждого вида на зону
        MaintenanceSchedule.objects.filter(
            kind=schedule.kind,
            year=schedule.year,
            zone=schedule.zone,
            status=MaintenanceSchedule.Status.APPROVED,
        ).exclude(pk=schedule.pk).update(status=MaintenanceSchedule.Status.DRAFT)
        log_action(request, "maintenance.schedule_approve", obj=schedule)
        return Response(self.get_serializer(schedule).data)

    @action(detail=True, methods=["post"])
    def discard(self, request, pk=None):
        schedule = self.get_object()
        if schedule.status == MaintenanceSchedule.Status.APPROVED:
            return Response({"detail": "Утверждённый график не удаляется"}, status=409)
        log_action(request, "maintenance.schedule_delete", payload={"title": schedule.title})
        schedule.delete()
        return Response(status=204)
