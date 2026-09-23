import pytest


@pytest.fixture(autouse=True)
def _isolated_infra(settings):
    # Юнит-тесты не зависят от Redis: слой каналов и кэш — в памяти
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.CELERY_TASK_ALWAYS_EAGER = True


@pytest.fixture
def tree(db):
    from apps.topology.models import Node, NodeKind

    district = Node.objects.add_root(create_kwargs={"name": "Район", "kind": NodeKind.DISTRICT})
    complex_ = Node.objects.add_child(district, {"name": "Объект Альфа", "kind": NodeKind.COMPLEX})
    house = Node.objects.add_child(complex_, {"name": "ДП Альфа", "kind": NodeKind.CONTROL_HOUSE})
    other = Node.objects.add_child(
        Node.objects.get(pk=district.pk), {"name": "Объект Бета", "kind": NodeKind.COMPLEX}
    )
    return {
        "district": district,
        "complex": Node.objects.get(pk=complex_.pk),
        "house": Node.objects.get(pk=house.pk),
        "other": Node.objects.get(pk=other.pk),
    }


@pytest.fixture
def roles(db):
    from apps.accounts.services import sync_roles

    sync_roles()


@pytest.fixture
def make_user(db, roles):
    from django.contrib.auth.models import Group

    from apps.accounts.models import User

    def _make(username, role, scope_node=None):
        user = User.objects.create_user(username=username, password="pass12345", scope_node=scope_node)
        user.groups.add(Group.objects.get(name=role))
        return User.objects.get(pk=user.pk)  # сброс кэша прав

    return _make
