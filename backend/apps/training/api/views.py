from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import log_action
from apps.topology.selectors import has_global_scope, user_scope_node

from .. import services
from ..models import TrainingSession


class LessonsView(APIView):
    """Уроки для ролей пользователя с лучшим результатом; в рабочем контуре доступна только экскурсия."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({"contour": settings.CONTOUR, "lessons": services.catalog(request.user)})


class CurrentView(APIView):
    """Текущее задание: шаги проверяются при каждом запросе."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        session = (
            TrainingSession.objects.filter(user=request.user)
            .exclude(status=TrainingSession.Status.ABANDONED)
            .select_related("node", "user")
            .first()
        )
        # завершённое показывается, пока ученик не закрыл итог
        if session is None or (
            session.status == TrainingSession.Status.DONE and session.context.get("dismissed")
        ):
            return Response(None)
        return Response(services.serialize(services.evaluate(session)))


class SessionsView(APIView):
    """Результаты: свои; руководителю и аналитику — сотрудников своей зоны."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = TrainingSession.objects.select_related("user", "node").exclude(
            status=TrainingSession.Status.ACTIVE
        )
        if request.user.has_perm("audit.view_actionlog"):
            if not has_global_scope(request.user):
                node = user_scope_node(request.user)
                qs = (
                    qs.filter(user__scope_node__path__startswith=node.path)
                    if node
                    else qs.filter(user=request.user)
                )
        else:
            qs = qs.filter(user=request.user)
        rows = []
        for s in qs[:200]:
            item = services.serialize(s)
            item["user"] = s.user.get_full_name() or s.user.username
            item.pop("steps")
            rows.append(item)
        return Response(rows)

    def post(self, request):
        try:
            session = services.start(request.user, request.data.get("lesson", ""))
        except services.TrainingError as exc:
            return Response({"detail": str(exc)}, status=409)
        log_action(request, "training.start", obj=session, payload={"lesson": session.lesson})
        return Response(services.serialize(session), status=201)


class SessionActionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk: int, action: str):
        session = get_object_or_404(
            TrainingSession.objects.select_related("node", "user"), pk=pk, user=request.user
        )
        try:
            if action == "confirm":
                session = services.confirm(session, request.data.get("step", ""))
            elif action == "hint":
                session.hints += 1
                session.save(update_fields=["hints"])
            elif action == "abandon":
                session = services.abandon(session)
                log_action(request, "training.abandon", obj=session)
            elif action == "dismiss":
                session.context["dismissed"] = True
                session.save(update_fields=["context"])
            else:
                return Response({"detail": "Неизвестное действие"}, status=404)
        except services.TrainingError as exc:
            return Response({"detail": str(exc)}, status=409)
        if session.status == TrainingSession.Status.DONE and action == "confirm":
            log_action(request, "training.done", obj=session)
        return Response(services.serialize(session))
