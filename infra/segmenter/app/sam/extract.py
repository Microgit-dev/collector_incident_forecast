"""Box-prompted building segmentation: image -> SAM masks -> pixel polygons.

Mirrors rooms_selector/cadastre_to_geojson.py's contour->polygon approach for
consistency, but uses RETR_EXTERNAL (not RETR_CCOMP): a building footprint
from a box-prompted single-object mask isn't expected to have interior
holes the way a wall mask's room cavities are.
"""

import cv2
import numpy as np

from app.sam.model import get_predictor

MIN_CONTOUR_AREA_PX = 20.0
SIMPLIFY_EPS_PX = 1.5


def mask_to_polygon_px(mask: np.ndarray, simplify_eps: float = SIMPLIFY_EPS_PX):
    mask_u8 = (mask.astype(np.uint8)) * 255
    contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < MIN_CONTOUR_AREA_PX:
        return None
    approx = cv2.approxPolyDP(contour, simplify_eps, closed=True)
    if len(approx) < 3:
        return None
    return approx[:, 0, :].tolist()  # [[x, y], ...] pixel space


def extract_building_masks(image_rgb: np.ndarray, box_px: tuple[float, float, float, float]):
    """Returns candidates sorted by score desc: [{"polygon_px": [...], "score": float}]."""
    predictor = get_predictor()
    predictor.set_image(image_rgb)
    box = np.array(box_px, dtype=np.float32)
    masks, scores, _ = predictor.predict(box=box, multimask_output=True)

    candidates = []
    for mask, score in sorted(zip(masks, scores), key=lambda m: -m[1]):
        polygon_px = mask_to_polygon_px(mask)
        if polygon_px is None:
            continue
        candidates.append({"polygon_px": polygon_px, "score": float(score)})
    return candidates
