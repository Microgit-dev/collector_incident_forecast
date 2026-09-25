from django.urls import path

from .views import CurrentView, LessonsView, SessionActionView, SessionsView

urlpatterns = [
    path("training/lessons/", LessonsView.as_view(), name="training-lessons"),
    path("training/sessions/", SessionsView.as_view(), name="training-sessions"),
    path("training/sessions/current/", CurrentView.as_view(), name="training-current"),
    path(
        "training/sessions/<int:pk>/<str:action>/",
        SessionActionView.as_view(),
        name="training-session-action",
    ),
]
