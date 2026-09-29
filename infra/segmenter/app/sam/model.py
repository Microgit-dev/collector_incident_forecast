"""Lazy-loaded SAM predictor singleton (vit_b by default, CPU inference)."""

import threading

from app import config

_predictor = None
_lock = threading.Lock()


def is_checkpoint_available() -> bool:
    return config.SAM_CHECKPOINT_PATH.exists()


def get_predictor():
    global _predictor
    if _predictor is not None:
        return _predictor
    with _lock:
        if _predictor is None:
            from segment_anything import SamPredictor, sam_model_registry

            if not is_checkpoint_available():
                raise FileNotFoundError(
                    f"SAM checkpoint not found at {config.SAM_CHECKPOINT_PATH} - see README setup steps"
                )
            sam = sam_model_registry[config.SAM_MODEL_TYPE](checkpoint=str(config.SAM_CHECKPOINT_PATH))
            sam.to(device="cpu")
            _predictor = SamPredictor(sam)
    return _predictor
