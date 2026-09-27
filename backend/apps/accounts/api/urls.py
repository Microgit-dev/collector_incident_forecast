from django.urls import path
from rest_framework.routers import DefaultRouter

from ..observability import SessionView, forward_auth
from .auth import AdminSessionView, LoginView, LogoutView, RefreshView
from .views import MeView, OperationsView, TeamViewSet

router = DefaultRouter()
router.register("teams", TeamViewSet, basename="team")

urlpatterns = [
    path("auth/token/", LoginView.as_view(), name="token_obtain"),
    path("auth/token/refresh/", RefreshView.as_view(), name="token_refresh"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("observability/session/", SessionView.as_view(), name="observability_session"),
    path("observability/auth/", forward_auth, name="observability_auth"),
    path("auth/admin-session/", AdminSessionView.as_view(), name="admin_session"),
    path("auth/operations/", OperationsView.as_view(), name="operations"),
    *router.urls,
]
