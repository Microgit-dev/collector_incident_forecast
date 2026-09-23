from django.db.models import QuerySet

from .models import Node

GLOBAL_SCOPE_PERM = "accounts.view_all_scopes"


def user_scope_node(user) -> Node | None:
    return getattr(user, "scope_node", None)


def has_global_scope(user) -> bool:
    return user.is_superuser or user.has_perm(GLOBAL_SCOPE_PERM)


def scope_queryset(qs: QuerySet, user, node_field: str) -> QuerySet:
    """
    Ограничивает выборку поддеревом зоны ответственности пользователя.
    `node_field` — путь до FK на Node (например, "node" или "channel__node").
    Пустая строка означает, что сам queryset состоит из Node.
    """
    if not user.is_authenticated:
        return qs.none()
    if has_global_scope(user):
        return qs
    node = user_scope_node(user)
    if node is None:
        return qs.none()
    lookup = f"{node_field}__path__startswith" if node_field else "path__startswith"
    return qs.filter(**{lookup: node.path})


def subtree(node: Node) -> QuerySet[Node]:
    return Node.objects.get_tree(node)


def ancestors_chain(node: Node) -> list[Node]:
    """Цепочка вверх от узла к корню: по ней идёт эскалация."""
    return [node, *reversed(Node.objects.get_ancestors(node))]
