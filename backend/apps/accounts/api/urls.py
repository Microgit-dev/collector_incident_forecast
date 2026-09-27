from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from ..observability import SessionView, forward_auth
from .auth import LoginView, LogoutView
from .views import MeView, TeamViewSet

router = DefaultRouter()
router.register("teams", TeamViewSet, basename="team")

urlpatterns = [
    path("auth/token/", LoginView.as_view(), name="token_obtain"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("observability/session/", SessionView.as_view(), name="observability_session"),
    path("observability/auth/", forward_auth, name="observability_auth"),
    *router.urls,
]
