"""
Настройки сервиса выделения зданий по снимку (порт building_selector из проекта radar).

Пути задаются переменными окружения: в контейнере чекпойнт SAM лежит в образе, кеш тайлов — в томе.
"""

import os
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SEGMENTER_DATA", SERVICE_DIR / "data"))
TILE_CACHE_DIR = Path(os.environ.get("SEGMENTER_TILE_CACHE", DATA_DIR / "tile_cache"))

SAM_MODEL_TYPE = os.environ.get("SAM_MODEL_TYPE", "vit_b")
SAM_CHECKPOINT_PATH = Path(
    os.environ.get("SAM_CHECKPOINT", DATA_DIR / "checkpoints" / "sam_vit_b_01ec64.pth")
)

ESRI_WORLD_IMAGERY_URL = os.environ.get(
    "SATELLITE_TILES",
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
)

# Границы масштаба и числа тайлов на один запрос: снимок и время инференса SAM ограничены.
MIN_ZOOM = 17
MAX_ZOOM = 20
MAX_TILES = 64
