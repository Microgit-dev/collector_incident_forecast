from django.db.models import Prefetch

from .models import Team, User


def teams_with_members():
    members = User.objects.filter(is_active=True).prefetch_related("groups").order_by("last_name")
    return (
        Team.objects.filter(is_active=True)
        .select_related("scope_node", "parent", "lead")
        .prefetch_related(Prefetch("members", queryset=members))
    )
