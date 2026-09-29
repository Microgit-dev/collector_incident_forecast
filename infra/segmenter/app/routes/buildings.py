import base64
from io import BytesIO

import numpy as np
from fastapi import APIRouter, HTTPException

from app import config
from app.geo import tiles, webmercator
from app.models import Candidate, ExtractBuildingRequest, ExtractBuildingResponse
from app.sam import extract as sam_extract
from app.sam.model import is_checkpoint_available

router = APIRouter()


def _fetch_best_available_crop(bbox, start_zoom: int, min_zoom: int):
    """Try zooms from start_zoom down to min_zoom, skipping any that exceed
    the tile budget or that Esri only has a "no imagery yet" placeholder for
    (common outside the US/Western Europe) - returns the first real crop
    found, at the highest zoom available.
    """
    last_error = None
    for zoom in range(start_zoom, min_zoom - 1, -1):
        tile_count = tiles.estimate_tile_count(bbox, zoom)
        if tile_count > config.MAX_TILES:
            last_error = (
                400,
                f"Selected area too large ({tile_count} tiles at zoom {zoom}, "
                f"max {config.MAX_TILES}) - draw a smaller selection",
            )
            continue
        try:
            cropped, origin_px, zoom, box_px = tiles.stitch_and_crop(bbox, zoom, config.TILE_CACHE_DIR)
        except Exception as e:
            last_error = (502, f"Failed to fetch satellite imagery: {e}")
            continue
        if tiles.is_placeholder_image(cropped):
            last_error = (404, "No aerial imagery available for this area at any usable zoom level")
            continue
        return cropped, origin_px, zoom, box_px

    status, message = last_error or (502, "Failed to fetch satellite imagery")
    raise HTTPException(status, message)


def _polygon_px_to_feature(polygon_px, origin_px, zoom: int, score: float) -> dict:
    ring = [
        list(webmercator.pixel_to_lonlat(origin_px[0] + x, origin_px[1] + y, zoom))
        for x, y in polygon_px
    ]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return {
        "type": "Feature",
        "properties": {"source": "sam", "score": score, "checkpoint": config.SAM_MODEL_TYPE},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


@router.post("/extract-building", response_model=ExtractBuildingResponse)
def extract_building(req: ExtractBuildingRequest) -> ExtractBuildingResponse:
    if not is_checkpoint_available():
        raise HTTPException(
            503,
            f"SAM checkpoint not found at {config.SAM_CHECKPOINT_PATH} - see README setup steps",
        )

    min_lon, min_lat, max_lon, max_lat = req.bbox
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(400, "Invalid bbox: min must be less than max on both axes")

    start_zoom = req.zoom or webmercator.pick_zoom_for_bbox(
        req.bbox, config.MAX_TILES, config.MIN_ZOOM, config.MAX_ZOOM
    )

    cropped, origin_px, zoom, box_px = _fetch_best_available_crop(
        req.bbox, start_zoom, config.MIN_ZOOM
    )

    image_rgb = np.array(cropped.convert("RGB"))
    h, w = image_rgb.shape[:2]
    if h < 8 or w < 8:
        raise HTTPException(400, "Selected area is too small")

    candidates_raw = sam_extract.extract_building_masks(image_rgb, box_px)
    if not candidates_raw:
        raise HTTPException(422, "No building outline found in the selected area")

    candidates = [
        Candidate(
            feature=_polygon_px_to_feature(c["polygon_px"], origin_px, zoom, c["score"]),
            score=c["score"],
        )
        for c in candidates_raw
    ]

    buf = BytesIO()
    cropped.save(buf, format="PNG")
    preview_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return ExtractBuildingResponse(
        feature=candidates[0].feature,
        candidates=candidates,
        preview_image=preview_b64,
        zoom_used=zoom,
    )
