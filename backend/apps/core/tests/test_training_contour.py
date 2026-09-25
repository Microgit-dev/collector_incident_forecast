"""Учебный контур: полигон в формате справочников заказчика грузится штатным импортом."""

from pathlib import Path

import pytest

POLYGON = Path(__file__).resolve().parents[4] / "simulator" / "polygon" / "dataset"

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(not POLYGON.exists(), reason="каталог полигона не смонтирован"),
]


@pytest.fixture
def polygon():
    from apps.assets.services import import_channels
    from apps.normalization.services import seed_default_taxonomy
    from apps.topology.services import import_objects

    seed_default_taxonomy()
    objects = import_objects(POLYGON / "справочник_объектов_диспетчер.csv")
    channels = import_channels(POLYGON / "справочник_каналов_датчиков.csv")
    return objects, channels


def test_polygon_loads_like_customer_reference(polygon):
    from apps.assets.models import Channel

    objects, channels = polygon
    assert objects["created"] == 13 and objects["orphans"] == 0
    assert channels["created"] == 183 and channels["unlinked"] == 0
    # пикеты разобраны тем же кодом, что у боевых каналов, — схема полигона строится без доработок
    assert Channel.objects.filter(picket__isnull=False).count() == channels["with_picket"] > 150
    # каждый тип датчика получил профиль нормализации
    assert not Channel.objects.filter(sensor_type__profile__isnull=True).exists()
    # идентификаторы вне диапазона заказчика
    assert Channel.objects.filter(external_id__lt=90_000_000).count() == 0


def test_demo_staff_get_polygon_scopes(polygon):
    from apps.accounts.demo import seed_demo
    from apps.accounts.models import User
    from apps.accounts.services import sync_roles

    sync_roles()
    seed_demo("x")
    assert User.objects.get(username="disp.petrov").scope_node.name == "объект Мю"
    assert User.objects.get(username="ods.ivanov").scope_node.depth == 1


def test_training_contour_skips_combat_only_schedules(settings):
    from django_celery_beat.models import PeriodicTask

    from apps.core.management.commands.bootstrap import COMBAT_ONLY, Command

    settings.CONTOUR = "training"
    Command()._schedules()
    tasks = set(PeriodicTask.objects.values_list("task", flat=True))
    assert tasks and not tasks & COMBAT_ONLY
    assert "apps.incidents.tasks.escalate_overdue_incidents" in tasks


def test_me_reports_contour(settings, client):
    from apps.accounts.models import User

    settings.CONTOUR = "training"
    user = User.objects.create_user("trainee", password="x")
    client.force_login(user)
    contour = client.get("/api/v1/auth/me/").json()["contour"]
    assert contour["code"] == "training" and contour["urls"]["combat"]
