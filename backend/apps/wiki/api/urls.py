from django.urls import path

from .views import WikiIndexView, WikiPageView

urlpatterns = [
    path("wiki/", WikiIndexView.as_view(), name="wiki-index"),
    path("wiki/<slug:slug>/", WikiPageView.as_view(), name="wiki-page"),
]
