from __future__ import annotations

from django.db.models import Q, QuerySet
from django.utils import timezone

from .models import Node, NodeKind

GLOBAL_SCOPE_PERM = "accounts.view_all_scopes"


def user_scope_node(user) -> Node | None:
    return getattr(user, "scope_node", None)


def has_global_scope(user) -> bool:
    return user.is_superuser or user.has_perm(GLOBAL_SCOPE_PERM)


def seconded_zones(user) -> list[Node]:
    """Зоны, куда сотрудник сейчас командирован (см. accounts.Secondment)."""
    if not getattr(user, "pk", None):
        return []
    now = timezone.now()
    return list(
        Node.objects.filter(
            secondments__user=user,
            secondments__starts_at__lte=now,
            secondments__ends_at__gt=now,
            secondments__cancelled_at__isnull=True,
        ).distinct()
    )


def scope_paths(user) -> list[str]:
    """Пути поддеревьев, которые видит пользователь: своя зона и зоны командирования."""
    node = user_scope_node(user)
    paths = [node.path] if node else []
    for zone in seconded_zones(user):
        if not any(zone.path.startswith(p) for p in paths):
            paths.append(zone.path)
    return paths


def scope_queryset(qs: QuerySet, user, node_field: str) -> QuerySet:
    """
    Ограничивает выборку поддеревом зоны ответственности пользователя (и зонами командирования).
    `node_field` — путь до FK на Node (например, "node" или "channel__node").
    Пустая строка означает, что сам queryset состоит из Node.
    """
    if not user.is_authenticated:
        return qs.none()
    if has_global_scope(user):
        return qs
    paths = scope_paths(user)
    if not paths:
        return qs.none()
    lookup = f"{node_field}__path__startswith" if node_field else "path__startswith"
    condition = Q()
    for path in paths:
        condition |= Q(**{lookup: path})
    return qs.filter(condition)


def in_scope(user, node: Node) -> bool:
    if has_global_scope(user):
        return True
    return any(node.path.startswith(p) for p in scope_paths(user))


def subtree(node: Node) -> QuerySet[Node]:
    return Node.objects.get_tree(node)


def ancestors_chain(node: Node) -> list[Node]:
    """Цепочка вверх от узла к корню: по ней идёт эскалация."""
    return [node, *reversed(Node.objects.get_ancestors(node))]


# ---------- объекты и зоны ----------
# Объект (комплекс) может стоять прямо под районом или внутри зоны ответственности, поэтому глубина
# объекта не фиксирована: объект узла ищется по виду, а не по уровню дерева.


class ObjectIndex:
    """Путь → объект для быстрого «к какому объекту относится узел/канал» без запросов в цикле."""

    def __init__(self, qs: QuerySet[Node] | None = None):
        objects = qs if qs is not None else Node.objects.filter(kind=NodeKind.COMPLEX)
        self.by_path = {n.path: n for n in objects}
        self.depths = sorted({len(p) for p in self.by_path})

    def of_path(self, path: str) -> Node | None:
        for length in self.depths:
            if length > len(path):
                break
            node = self.by_path.get(path[:length])
            if node is not None:
                return node
        return None

    def __iter__(self):
        return iter(self.by_path.values())


def object_of(node: Node) -> Node | None:
    """Объект, в который входит узел (сам узел, если он объект)."""
    if node.kind == NodeKind.COMPLEX:
        return node
    return Node.objects.filter(
        kind=NodeKind.COMPLEX,
        path__in=[node.path[:i] for i in range(Node.steplen, len(node.path), Node.steplen)],
    ).first()


def zone_of(node: Node) -> Node | None:
    """Зона ответственности, в которую входит узел (или сам узел-зона)."""
    if node.kind == NodeKind.ZONE:
        return node
    prefixes = [node.path[:i] for i in range(Node.steplen, len(node.path), Node.steplen)]
    return Node.objects.filter(kind=NodeKind.ZONE, path__in=prefixes).order_by("-depth").first()


def objects_under(node: Node | None) -> QuerySet[Node]:
    qs = Node.objects.filter(kind=NodeKind.COMPLEX, is_active=True)
    return qs.filter(path__startswith=node.path) if node is not None else qs
