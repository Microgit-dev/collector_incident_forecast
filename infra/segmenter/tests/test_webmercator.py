from app.geo.webmercator import (
    bbox_to_tile_range,
    lonlat_to_pixel,
    pick_zoom_for_bbox,
    pixel_to_lonlat,
    tile_count_for_bbox,
)


def test_pixel_roundtrip():
    zoom = 18
    lon, lat = 37.5546, 55.6963  # NUST MISIS campus, Moscow
    px, py = lonlat_to_pixel(lon, lat, zoom)
    lon2, lat2 = pixel_to_lonlat(px, py, zoom)
    assert abs(lon - lon2) < 1e-9
    assert abs(lat - lat2) < 1e-9


def test_pixel_increases_east_and_south():
    zoom = 18
    x0, y0 = lonlat_to_pixel(37.55, 55.70, zoom)
    x1, y1 = lonlat_to_pixel(37.56, 55.69, zoom)  # further east, further south
    assert x1 > x0
    assert y1 > y0  # web mercator y grows southward


def test_bbox_to_tile_range_is_small_for_a_building_sized_bbox():
    bbox = (37.5540, 55.6960, 37.5552, 55.6968)
    x0, y0, x1, y1 = bbox_to_tile_range(bbox, 19)
    assert x0 <= x1
    assert y0 <= y1
    # ~75m x 88m bbox at zoom 19 (~0.17 m/px here) spans ~2-3 tiles per axis
    # depending on tile-boundary alignment - a handful of tiles either way.
    assert (x1 - x0 + 1) * (y1 - y0 + 1) <= 9


def test_pick_zoom_respects_max_tiles():
    bbox = (37.550, 55.695, 37.560, 55.700)  # ~700m x ~550m, fits the budget somewhere in range
    zoom = pick_zoom_for_bbox(bbox, max_tiles=64, min_zoom=15, max_zoom=20)
    assert tile_count_for_bbox(bbox, zoom) <= 64
    assert 15 <= zoom <= 20


def test_pick_zoom_falls_back_to_min_zoom_for_oversized_area():
    bbox = (37.50, 55.65, 37.60, 55.75)  # ~11km x 11km - too large for max_tiles at any allowed zoom
    zoom = pick_zoom_for_bbox(bbox, max_tiles=64, min_zoom=15, max_zoom=20)
    assert zoom == 15  # best effort: the lowest (widest-coverage) zoom allowed
    # the fallback does NOT guarantee the cap is respected - callers (the API
    # route) must check tile_count_for_bbox() themselves and reject.
    assert tile_count_for_bbox(bbox, zoom) > 64


def test_pick_zoom_prefers_higher_detail_when_it_fits():
    bbox = (37.5540, 55.6960, 37.5552, 55.6968)  # building-sized
    zoom = pick_zoom_for_bbox(bbox, max_tiles=64, min_zoom=17, max_zoom=20)
    assert zoom == 20
