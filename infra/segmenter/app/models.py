from pydantic import BaseModel, Field


class ExtractBuildingRequest(BaseModel):
    bbox: tuple[float, float, float, float] = Field(
        ..., description="min_lon, min_lat, max_lon, max_lat"
    )
    zoom: int | None = None


class Candidate(BaseModel):
    feature: dict
    score: float


class ExtractBuildingResponse(BaseModel):
    feature: dict
    candidates: list[Candidate]
    preview_image: str  # base64-encoded PNG
    zoom_used: int


class HealthResponse(BaseModel):
    ok: bool
    checkpoint_available: bool
