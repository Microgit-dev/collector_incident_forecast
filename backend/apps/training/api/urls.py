from django.urls import path

from .exercises import (
    ExerciseActionView,
    ExerciseDetailView,
    ExerciseOptionsView,
    ExercisesView,
    MyExercisesView,
)
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
    path("exercises/", ExercisesView.as_view(), name="exercises"),
    path("exercises/options/", ExerciseOptionsView.as_view(), name="exercise-options"),
    path("exercises/mine/", MyExercisesView.as_view(), name="exercises-mine"),
    path("exercises/<int:pk>/", ExerciseDetailView.as_view(), name="exercise-detail"),
    path("exercises/<int:pk>/<str:action>/", ExerciseActionView.as_view(), name="exercise-action"),
]
