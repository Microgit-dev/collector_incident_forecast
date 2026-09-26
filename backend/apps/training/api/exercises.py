from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import log_action

from .. import exercises as svc
from ..models import Exercise, ExerciseParticipant


def _visible(user):
    """Руководителю — учения его зоны; остальным — те, где он участник."""
    qs = Exercise.objects.select_related("node", "created_by", "stopped_by").prefetch_related(
        "participants__user"
    )
    if svc.can_manage(user):
        scope = svc.managed_nodes(user)
        if scope is None:
            return qs
        return qs.filter(Q(node__path__startswith=scope.path) | Q(participants__user=user)).distinct()
    return qs.filter(participants__user=user)


class ExerciseOptionsView(APIView):
    """Что можно выбрать при настройке: сценарии, осложнения, объекты полигона и сотрудники."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not svc.can_manage(request.user):
            return Response({"detail": "Учения настраивает руководитель"}, status=403)
        objects = svc.polygon_objects(request.user)
        node = next((n for n in objects if str(n.pk) == request.query_params.get("node")), None) or (
            objects[0] if objects else None
        )
        return Response(
            {
                "scenarios": [
                    {"code": s.code, "title": s.title, "description": s.description}
                    for s in svc.SCENARIOS.values()
                ],
                "complications": [{"code": k, "title": v} for k, v in svc.COMPLICATIONS.items()],
                "objects": [{"id": n.pk, "name": n.name} for n in objects],
                "node": node.pk if node else None,
                "candidates": svc.candidates(request.user, node) if node else [],
            }
        )


class ExercisesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response([svc.serialize(e, request.user) for e in _visible(request.user)[:100]])

    def post(self, request):
        if not svc.can_manage(request.user):
            return Response({"detail": "Учения настраивает руководитель"}, status=403)
        data = dict(request.data)
        raw = request.data.get("scheduled_at")
        if raw:
            when = parse_datetime(raw)
            if when is None:
                return Response({"detail": "Неверное время начала"}, status=400)
            data["scheduled_at"] = when if timezone.is_aware(when) else timezone.make_aware(when)
        try:
            exercise = svc.create(request.user, data)
        except (svc.ExerciseError, ValueError, TypeError) as exc:
            return Response({"detail": str(exc)}, status=400)
        log_action(
            request,
            "exercise.create",
            obj=exercise,
            payload={"scenario": exercise.scenario, "participants": exercise.participants.count()},
        )
        return Response(svc.serialize(exercise, request.user), status=201)


class MyExercisesView(APIView):
    """Предстоящие и идущие учения, в которых я участник, — для плашки над рабочим местом."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = _visible(request.user).filter(
            participants__user=request.user,
            status__in=[Exercise.Status.SCHEDULED, Exercise.Status.RUNNING],
        )
        return Response([svc.serialize(e, request.user) for e in qs.order_by("scheduled_at")])


class ExerciseDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk: int):
        exercise = get_object_or_404(_visible(request.user), pk=pk)
        return Response(svc.serialize(exercise, request.user))


class ExerciseActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int, action: str):
        exercise = get_object_or_404(_visible(request.user), pk=pk)
        if action == "confirm":
            updated = ExerciseParticipant.objects.filter(
                exercise=exercise, user=request.user, confirmed_at=None
            ).update(confirmed_at=timezone.now())
            if updated:
                log_action(request, "exercise.confirm", obj=exercise)
            return Response(svc.serialize(Exercise.objects.get(pk=pk), request.user))
        if not svc.can_manage(request.user, exercise):
            return Response({"detail": "Управляет учениями руководитель"}, status=403)
        reason = (request.data.get("reason") or "").strip()[:255]
        try:
            if action == "start":
                exercise = svc.start(exercise, request.user)
            elif action == "finish":
                exercise = svc.finish(exercise, request.user)
            elif action == "stop":
                exercise = svc.finish(exercise, request.user, early=True, reason=reason)
            else:
                return Response({"detail": "Неизвестное действие"}, status=404)
        except svc.ExerciseError as exc:
            return Response({"detail": str(exc)}, status=409)
        log_action(
            request, f"exercise.{action}", obj=exercise, payload={"reason": reason} if reason else None
        )
        return Response(svc.serialize(Exercise.objects.get(pk=pk), request.user))
