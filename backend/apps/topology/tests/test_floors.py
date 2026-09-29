import io

import httpx
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.assets.models import Channel
from apps.topology import geo, georef, segment, structure
from apps.topology.models import Floor, Node

BUILDING = {
    "type": "Polygon",
    "coordinates": [
        [[37.6040, 55.7040], [37.6050, 55.7040], [37.6050, 55.7045], [37.6040, 55.7045], [37.6040, 55.7040]]
    ],
}


def _png(width=400, height=200, fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format=fmt)
    return SimpleUploadedFile(f"plan.{fmt.lower()}", buf.getvalue(), content_type=f"image/{fmt.lower()}")


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _pixel_points(width=400, height=200):
    """Углы плана → углы здания BUILDING: план лежит ровно на контуре (север вверху)."""
    (w, s), (e, n) = BUILDING["coordinates"][0][0], BUILDING["coordinates"][0][2]
    return [
        {"px": 0, "py": 0, "lon": w, "lat": n},
        {"px": width, "py": 0, "lon": e, "lat": n},
        {"px": width, "py": height, "lon": e, "lat": s},
        {"px": 0, "py": height, "lon": w, "lat": s},
    ]


@pytest.fixture
def site(tree, make_user):
    head = make_user("head", "head", tree["district"])
    obj = tree["complex"]
    Node.objects.filter(pk=obj.pk).update(geometry=BUILDING)
    return {"head": head, "obj": Node.objects.get(pk=obj.pk), "house": tree["house"], "other": tree["other"]}


# ---------- подгонка ----------


def test_fit_recovers_corners_and_center():
    points = georef.clean_points(_pixel_points())
    result = georef.fit(points, 400, 200)
    corners = result.corners(400, 200)
    assert corners[0] == pytest.approx([37.604, 55.7045], abs=1e-7)
    assert corners[2] == pytest.approx([37.605, 55.704], abs=1e-7)
    # середина плана — середина здания; невязка точной подгонки — ноль
    lon, lat = result.to_lonlat(200, 100)
    assert (lon, lat) == pytest.approx((37.6045, 55.70425), abs=1e-6)
    assert result.rmse_m < 0.01 and result.used == 4


def test_fit_rmse_reports_bad_point_in_meters():
    points = _pixel_points()
    points.append({"px": 200, "py": 100, "lon": 37.6046, "lat": 55.70425})  # ~6 м мимо центра
    result = georef.fit(georef.clean_points(points), 400, 200)
    assert 1 < result.rmse_m < 6


def test_fit_rejects_collinear_and_too_few_points():
    line = [{"px": x, "py": 10, "lon": 37.6 + x * 1e-6, "lat": 55.7} for x in (0, 100, 200, 300)]
    with pytest.raises(georef.GeorefError, match="одной линии"):
        georef.fit(georef.clean_points(line), 400, 200)
    with pytest.raises(georef.GeorefError, match="не меньше"):
        georef.fit(georef.clean_points(_pixel_points()[:2]), 400, 200)
    # выключенная точка не участвует в подгонке
    points = georef.clean_points(_pixel_points())
    points[0]["on"] = points[1]["on"] = False
    with pytest.raises(georef.GeorefError):
        georef.fit(points, 400, 200)


def test_clean_points_validates_ranges():
    with pytest.raises(georef.GeorefError):
        georef.clean_points([{"px": 1, "py": 1, "lon": 200, "lat": 55}])
    with pytest.raises(georef.GeorefError):
        georef.clean_points([{"px": 1, "py": 1}])


# ---------- этажи через API ----------


def test_floor_lifecycle_base_floor_and_georef(site):
    client = _client(site["head"])
    obj = site["obj"]
    r = client.post(
        f"/api/v1/topology/objects/{obj.pk}/floors/", {"level": 1, "plan": _png()}, format="multipart"
    )
    assert r.status_code == 201, r.data
    first = r.data
    assert first["is_base"] and (first["width"], first["height"]) == (400, 200) and first["corners"] is None
    # второй этаж — не контрольный; тот же номер этажа второй раз нельзя
    second = client.post(
        f"/api/v1/topology/objects/{obj.pk}/floors/",
        {"level": 2, "name": "Второй", "plan": _png()},
        format="multipart",
    ).data
    assert not second["is_base"] and second["title"] == "Второй"
    assert (
        client.post(
            f"/api/v1/topology/objects/{obj.pk}/floors/", {"level": 2}, format="multipart"
        ).status_code
        == 400
    )

    # контрольные точки → углы плана на местности
    r = client.patch(f"/api/v1/topology/floors/{first['id']}/", {"points": _pixel_points()}, format="json")
    assert r.status_code == 200, r.data
    assert r.data["corners"][0] == pytest.approx([37.604, 55.7045], abs=1e-7) and r.data["rmse_m"] < 0.01

    # сделать второй контрольным — первый перестаёт им быть
    client.patch(f"/api/v1/topology/floors/{second['id']}/", {"is_base": True}, format="json")
    assert list(Floor.objects.filter(is_base=True).values_list("pk", flat=True)) == [second["id"]]

    # план отдаётся файлом; список этажей — по возрастанию
    plan = client.get(f"/api/v1/topology/floors/{first['id']}/plan/")
    assert plan.status_code == 200 and b"".join(plan.streaming_content)[:4] == b"\x89PNG"
    levels = [f["level"] for f in client.get(f"/api/v1/topology/objects/{obj.pk}/floors/").data]
    assert levels == [1, 2]

    # удалили контрольный — контрольным становится оставшийся
    assert client.delete(f"/api/v1/topology/floors/{second['id']}/").status_code == 204
    assert Floor.objects.get().is_base


def test_new_plan_of_other_size_drops_points(site):
    floor = structure_floor(site)
    client = _client(site["head"])
    client.patch(f"/api/v1/topology/floors/{floor.pk}/", {"points": _pixel_points()}, format="json")
    r = client.patch(f"/api/v1/topology/floors/{floor.pk}/", {"plan": _png(800, 300)}, format="multipart")
    assert r.status_code == 200, r.data
    assert r.data["points"] == [] and r.data["corners"] is None and r.data["width"] == 800


def test_plan_must_be_an_image(site):
    client = _client(site["head"])
    bad = SimpleUploadedFile("plan.png", b"not an image", content_type="image/png")
    r = client.post(
        f"/api/v1/topology/objects/{site['obj'].pk}/floors/", {"level": 1, "plan": bad}, format="multipart"
    )
    assert r.status_code == 400 and "изображение" in r.data["detail"]


def test_floors_respect_zone_scope(site, make_user):
    floor = structure_floor(site)
    stranger = make_user("stranger", "head", site["other"])
    client = _client(stranger)
    assert client.get(f"/api/v1/topology/floors/{floor.pk}/plan/").status_code == 404
    assert (
        client.patch(f"/api/v1/topology/floors/{floor.pk}/", {"name": "x"}, format="json").status_code == 400
    )
    dispatcher = make_user("disp", "unit_dispatcher", site["obj"])
    # диспетчер своей зоны видит план, но не правит этажи
    assert _client(dispatcher).get(f"/api/v1/topology/floors/{floor.pk}/plan/").status_code == 200
    assert (
        _client(dispatcher)
        .patch(f"/api/v1/topology/floors/{floor.pk}/", {"name": "x"}, format="json")
        .status_code
        == 400
    )


def structure_floor(site) -> Floor:
    from apps.topology import floors

    return floors.create_floor(site["head"], site["obj"], level=1, plan=_png())


def test_sensor_is_placed_on_floor_of_its_object(site, make_user):
    floor = structure_floor(site)
    head = make_user("analyst", "analyst", site["obj"].get_parent())  # датчики заводит аналитик
    channel = structure.create_sensor(
        head, node_id=site["house"].pk, name="Датчик ПК1", location=[37.6045, 55.7042], floor_id=floor.pk
    )
    assert channel.floor_id == floor.pk
    other = structure.create_sensor(head, node_id=site["other"].pk, name="Чужой")
    with pytest.raises(structure.StructureError, match="Этаж"):
        structure.attach_sensor(head, other, floor_id=floor.pk)
    # перенос датчика на другой объект снимает этаж прежнего
    structure.attach_sensor(head, channel, node_id=site["other"].pk)
    assert Channel.objects.get(pk=channel.pk).floor_id is None


# ---------- выделение здания по снимку ----------


def test_prompt_bbox_pads_hint_and_limits_size():
    box = segment.prompt_bbox(37.6045, 55.70425, BUILDING)
    assert box[0] < 37.604 and box[2] > 37.605
    square = segment.prompt_bbox(37.6, 55.7, None)
    assert square[2] - square[0] > 0 and square[3] - square[1] > 0
    huge = {"type": "Polygon", "coordinates": [[[37.6, 55.7], [37.62, 55.7], [37.62, 55.71], [37.6, 55.7]]]}
    with pytest.raises(geo.GeoError, match="400"):
        segment.prompt_bbox(37.61, 55.705, huge)


def _osm(monkeypatch):
    monkeypatch.setattr(
        geo,
        "detect_building",
        lambda lon, lat: {
            "geometry": BUILDING,
            "source": "osm:way/1",
            "name": "",
            "address": "",
            "levels": None,
            "area_m2": 3500,
            "center": [37.6045, 55.70425],
            "exact": True,
        },
    )


@override_settings(SEGMENTER_URL="")
def test_segment_without_ai_service_falls_back_to_osm(site, monkeypatch):
    _osm(monkeypatch)
    r = _client(site["head"]).post(
        "/api/v1/topology/segment-building/", {"lon": 37.6045, "lat": 55.70425}, format="json"
    )
    assert r.status_code == 200 and r.data["source"] == "osm:way/1" and "не подключён" in r.data["note"]


@override_settings(SEGMENTER_URL="http://segmenter:8000")
def test_segment_uses_ai_candidates(site, monkeypatch):
    feature = {"type": "Feature", "geometry": BUILDING, "properties": {}}
    calls = {}

    def fake_post(url, json, timeout):
        calls["url"], calls["bbox"] = url, json["bbox"]
        body = {"candidates": [{"feature": feature, "score": 0.97}], "zoom_used": 19}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(segment.httpx, "post", fake_post)
    r = _client(site["head"]).post(
        "/api/v1/topology/segment-building/",
        {"lon": 37.6045, "lat": 55.70425, "hint": BUILDING},
        format="json",
    )
    assert r.status_code == 200, r.data
    assert r.data["source"] == "sam" and r.data["score"] == 0.97 and r.data["zoom"] == 19
    assert calls["url"].endswith("/api/extract-building") and calls["bbox"][0] < 37.604


@override_settings(SEGMENTER_URL="http://segmenter:8000")
def test_segment_service_down_falls_back_with_note(site, monkeypatch):
    _osm(monkeypatch)

    def down(*args, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(segment.httpx, "post", down)
    r = _client(site["head"]).post(
        "/api/v1/topology/segment-building/", {"lon": 37.6045, "lat": 55.70425}, format="json"
    )
    assert r.status_code == 200 and r.data["source"].startswith("osm") and "недоступен" in r.data["note"]
