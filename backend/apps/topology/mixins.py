from .selectors import scope_queryset


class ScopedQuerySetMixin:
    """DRF-вьюсет видит только объекты из зоны ответственности пользователя."""

    scope_field = "node"

    def get_queryset(self):
        return scope_queryset(super().get_queryset(), self.request.user, self.scope_field)
