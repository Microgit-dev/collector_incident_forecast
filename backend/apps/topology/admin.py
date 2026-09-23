from django.contrib import admin
from treebeard.admin import TreeAdmin
from treebeard.forms import movenodeform_factory

from .models import Node


@admin.register(Node)
class NodeAdmin(TreeAdmin):
    form = movenodeform_factory(Node)
    list_display = ("name", "kind", "external_id", "picket_from", "picket_to", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("name", "external_id")
