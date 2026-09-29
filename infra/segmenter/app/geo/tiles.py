"""Fetch, disk-cache, stitch and crop Esri World Imagery tiles for a bbox.

Tiles are cached on disk: the prototype is a non-commercial, internal tool,
which is the condition under which Esri's free tile terms allow local reuse.
For the customer's closed network, point SATELLITE_TILES at their own tile
server (see app/config.py).
"""

import math
from io import BytesIO
from pathlib import Path

import numpy as np
import requests
from PIL import Image

from app import config
from app.geo.webmercator import TILE_SIZE, lonlat_to_pixel

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "collector-forecast-segmenter/1.0"})

# SAM's box prompt needs surrounding context to tell "inside the box" from
# "outside" - a box that exactly touches the image edges (i.e. fetching only
# the user's selection, no more) is a degenerate prompt and produces
# nonsense masks (confirmed empirically: it traced a road, not a building).
# So the fetched/stitched image is padded well beyond the user's selection,
# and the selection itself becomes the box prompt *within* that larger image.
DEFAULT_PAD_FRACTION = 0.6
MIN_PAD_PX = 48

# Esri serves a flat gray "Map data not yet available" placeholder (HTTP 200,
# not an error) for zooms beyond what's actually captured in a given region -
# common outside the US/Western Europe. Real aerial imagery has plenty of
# texture; empirically, placeholder tiles measure ~5-6 std (grayscale) vs
# ~60+ for real imagery, so 20 leaves a wide safety margin either way.
PLACEHOLDER_STD_THRESHOLD = 20.0


def is_placeholder_image(image: Image.Image, std_threshold: float = PLACEHOLDER_STD_THRESHOLD) -> bool:
    arr = np.asarray(image.convert("L"), dtype=np.float32)
    return float(arr.std()) < std_threshold


def _tile_cache_path(cache_dir: Path, zoom: int, x: int, y: int) -> Path:
    return cache_dir / str(zoom) / str(x) / f"{y}.png"


def fetch_tile(zoom: int, x: int, y: int, cache_dir: Path = config.TILE_CACHE_DIR) -> Image.Image:
    cache_path = _tile_cache_path(cache_dir, zoom, x, y)
    if cache_path.exists():
        return Image.open(cache_path).convert("RGB")

    url = config.ESRI_WORLD_IMAGERY_URL.format(z=zoom, x=x, y=y)
    resp = _SESSION.get(url, timeout=15)
    resp.raise_for_status()
    image = Image.open(BytesIO(resp.content)).convert("RGB")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(cache_path, format="PNG")
    return image


def _padded_pixel_rect(bbox, zoom: int, pad_fraction: float):
    """Returns (px0, py0, px1, py1) of the user's selection, and the padded
    fetch rect (crop_x0, crop_y0, crop_x1, crop_y1) around it, all in world
    pixel space at `zoom`."""
    min_lon, min_lat, max_lon, max_lat = bbox
    px0, py0 = lonlat_to_pixel(min_lon, max_lat, zoom)  # selection top-left
    px1, py1 = lonlat_to_pixel(max_lon, min_lat, zoom)  # selection bottom-right

    pad_x = max((px1 - px0) * pad_fraction, MIN_PAD_PX)
    pad_y = max((py1 - py0) * pad_fraction, MIN_PAD_PX)

    crop_rect = (px0 - pad_x, py0 - pad_y, px1 + pad_x, py1 + pad_y)
    return (px0, py0, px1, py1), crop_rect


def _tile_range_for_pixel_rect(rect):
    x0, y0, x1, y1 = rect
    tile_x0 = max(0, int(math.floor(x0 / TILE_SIZE)))
    tile_y0 = max(0, int(math.floor(y0 / TILE_SIZE)))
    tile_x1 = max(tile_x0, int(math.floor((x1 - 1e-9) / TILE_SIZE)))
    tile_y1 = max(tile_y0, int(math.floor((y1 - 1e-9) / TILE_SIZE)))
    return tile_x0, tile_y0, tile_x1, tile_y1


def estimate_tile_count(bbox, zoom: int, pad_fraction: float = DEFAULT_PAD_FRACTION) -> int:
    """Tile count stitch_and_crop would actually fetch, including padding -
    used by the API route to reject oversized requests before fetching."""
    _, crop_rect = _padded_pixel_rect(bbox, zoom, pad_fraction)
    tile_x0, tile_y0, tile_x1, tile_y1 = _tile_range_for_pixel_rect(crop_rect)
    return (tile_x1 - tile_x0 + 1) * (tile_y1 - tile_y0 + 1)


def stitch_and_crop(bbox, zoom: int, cache_dir: Path = config.TILE_CACHE_DIR,
                     pad_fraction: float = DEFAULT_PAD_FRACTION):
    """Returns (cropped_image, crop_origin_px, zoom, box_px).

    cropped_image covers the user's selection PLUS padding, so SAM has
    context beyond the prompt box. box_px is the user's original selection
    rectangle in the cropped image's local pixel coordinates - that's the
    SAM box prompt. crop_origin_px is the (x, y) world-pixel coordinate (at
    `zoom`) of the cropped image's top-left corner, for mapping any pixel
    in it back to lon/lat via pixel_to_lonlat().
    """
    (px0, py0, px1, py1), crop_rect = _padded_pixel_rect(bbox, zoom, pad_fraction)
    tile_x0, tile_y0, tile_x1, tile_y1 = _tile_range_for_pixel_rect(crop_rect)

    grid_w = (tile_x1 - tile_x0 + 1) * TILE_SIZE
    grid_h = (tile_y1 - tile_y0 + 1) * TILE_SIZE
    stitched = Image.new("RGB", (grid_w, grid_h))

    for tx in range(tile_x0, tile_x1 + 1):
        for ty in range(tile_y0, tile_y1 + 1):
            tile = fetch_tile(zoom, tx, ty, cache_dir)
            stitched.paste(tile, ((tx - tile_x0) * TILE_SIZE, (ty - tile_y0) * TILE_SIZE))

    stitched_origin_px = (tile_x0 * TILE_SIZE, tile_y0 * TILE_SIZE)

    crop_x0, crop_y0, crop_x1, crop_y1 = crop_rect
    crop_box = (
        int(round(crop_x0 - stitched_origin_px[0])),
        int(round(crop_y0 - stitched_origin_px[1])),
        int(round(crop_x1 - stitched_origin_px[0])),
        int(round(crop_y1 - stitched_origin_px[1])),
    )
    cropped = stitched.crop(crop_box)
    crop_origin_px = (crop_x0, crop_y0)

    box_px = (px0 - crop_x0, py0 - crop_y0, px1 - crop_x0, py1 - crop_y0)
    return cropped, crop_origin_px, zoom, box_px
