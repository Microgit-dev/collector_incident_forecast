from apps.assets.models import Channel, Equipment, IncidentDomain, SensorType
from apps.assets.registry import emulate_registry


def _channel(node, ext_id, type_name, picket=None):
    st, _ = SensorType.objects.get_or_create(name=type_name, defaults={"domain": IncidentDomain.FIRE})
    return Channel.objects.create(
        external_id=ext_id, node=node, sensor_type=st, name=f"{type_name} {ext_id}", picket=picket
    )


def test_registry_is_deterministic_and_groups_cabinet_signals(tree):
    _channel(tree["house"], 1, "Датчик дыма", picket=12)
    _channel(tree["house"], 2, "Газовый датчик")
    _channel(tree["house"], 3, "Состояние фазы")
    _channel(tree["house"], 4, "Переключатель")
    _channel(tree["house"], 5, "Неизвестный тип")

    first = emulate_registry()
    assert first["equipment"] == 3 and first["cabinets"] == 1
    cabinet = Equipment.objects.get(kind="cabinet")
    assert cabinet.channels.count() == 2
    smoke = Equipment.objects.get(inventory_number="EMU-1")
    assert (smoke.mtbf_hours, smoke.maintenance_interval_days, smoke.picket) == (60_000, 90, 12)

    snapshot = list(
        Equipment.objects.order_by("inventory_number").values_list(
            "inventory_number", "commissioned_at", "last_maintenance_at"
        )
    )
    emulate_registry()
    assert (
        list(
            Equipment.objects.order_by("inventory_number").values_list(
                "inventory_number", "commissioned_at", "last_maintenance_at"
            )
        )
        == snapshot
    )


def test_manual_records_survive_rebuild(tree):
    Equipment.objects.create(kind="pump", node=tree["house"], name="Насос (вручную)", source="manual")
    emulate_registry()
    assert Equipment.objects.filter(source="manual").count() == 1
