from rest_framework.permissions import BasePermission, DjangoModelPermissions


class RoleModelPermissions(DjangoModelPermissions):
    """
    RBAC поверх стандартных Django-permissions: роли — это Groups (см. accounts.roles),
    а чтение тоже требует права view_*, в отличие от базового DjangoModelPermissions.
    """

    perms_map = {
        **DjangoModelPermissions.perms_map,
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "HEAD": ["%(app_label)s.view_%(model_name)s"],
    }


def require_perm(perm: str) -> type[BasePermission]:
    """Permission-класс для действий, не сводимых к CRUD: require_perm('incidents.decide_incident')."""

    class _RequirePerm(BasePermission):
        def has_permission(self, request, view):
            return bool(request.user and request.user.is_authenticated and request.user.has_perm(perm))

    _RequirePerm.__name__ = f"RequirePerm_{perm.replace('.', '_')}"
    return _RequirePerm
