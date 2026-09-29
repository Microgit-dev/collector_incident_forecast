"""
Сервис ИИ-выделения зданий: рамка на карте → снимок Esri World Imagery → Segment Anything → контур GeoJSON.

Вызывается бэкендом (apps/topology/segment.py) по адресу SEGMENTER_URL; наружу не публикуется.
"""

from fastapi import FastAPI

from app.models import HealthResponse
from app.routes import buildings
from app.sam.model import is_checkpoint_available

app = FastAPI(title="Segmenter")

app.include_router(buildings.router, prefix="/api")


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(ok=True, checkpoint_available=is_checkpoint_available())
