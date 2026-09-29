"""Standard Web Mercator (EPSG:3857) "slippy map" tile math.

Esri World Imagery tiles are already served in this projection, so no real
geodesic library (pyproj/mercantile) is needed - just the handful of
closed-form formulas every XYZ tile server uses. Coordinates are
(lon, lat) in degrees (GeoJSON order), pixel coordinates are in the global
pixel grid at a given zoom (tile (0,0)'s top-left corner is pixel (0,0)).
"""

import math

TILE_SIZE = 256
BBox = tuple  # (min_lon, min_lat, max_lon, max_lat)


def lonlat_to_pixel(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    scale = TILE_SIZE * (2 ** zoom)
    x = (lon + 180.0) / 360.0 * scale
    sin_lat = math.sin(lat * math.pi / 180.0)
    sin_lat = min(max(sin_lat, -0.9999), 0.9999)
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * scale
    return x, y


def pixel_to_lonlat(px: float, py: float, zoom: int) -> tuple[float, float]:
    scale = TILE_SIZE * (2 ** zoom)
    lon = px / scale * 360.0 - 180.0
    n = math.pi - 2 * math.pi * py / scale
    lat = 180.0 / math.pi * math.atan(0.5 * (math.exp(n) - math.exp(-n)))
    return lon, lat


def bbox_to_tile_range(bbox, zoom: int) -> tuple[int, int, int, int]:
    """Returns (tile_x0, tile_y0, tile_x1, tile_y1) inclusive, covering bbox."""
    min_lon, min_lat, max_lon, max_lat = bbox
    x0, y0 = lonlat_to_pixel(min_lon, max_lat, zoom)  # top-left (max lat = smaller y)
    x1, y1 = lonlat_to_pixel(max_lon, min_lat, zoom)  # bottom-right
    tile_x0 = max(0, int(math.floor(x0 / TILE_SIZE)))
    tile_y0 = max(0, int(math.floor(y0 / TILE_SIZE)))
    tile_x1 = int(math.floor((x1 - 1e-9) / TILE_SIZE))
    tile_y1 = int(math.floor((y1 - 1e-9) / TILE_SIZE))
    tile_x1 = max(tile_x0, tile_x1)
    tile_y1 = max(tile_y0, tile_y1)
    return tile_x0, tile_y0, tile_x1, tile_y1


def tile_count_for_bbox(bbox, zoom: int) -> int:
    x0, y0, x1, y1 = bbox_to_tile_range(bbox, zoom)
    return (x1 - x0 + 1) * (y1 - y0 + 1)


def pick_zoom_for_bbox(bbox, max_tiles: int, min_zoom: int, max_zoom: int) -> int:
    """Highest zoom (most detail) whose tile grid for bbox stays within max_tiles.

    If the bbox is too large to fit within max_tiles even at min_zoom, returns
    min_zoom anyway (best effort) - the tile count at that zoom may still
    exceed max_tiles, so callers that need a hard cap must check
    tile_count_for_bbox() themselves and reject oversized requests.
    """
    for zoom in range(max_zoom, min_zoom - 1, -1):
        if tile_count_for_bbox(bbox, zoom) <= max_tiles:
            return zoom
    return min_zoom
