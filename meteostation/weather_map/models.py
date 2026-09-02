from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class WeatherMapLayer(BaseModel):
    id: str
    label: str
    description: str
    status: str
    recipe: dict[str, object] = Field(default_factory=dict)


class WeatherMapOverlay(BaseModel):
    id: str
    label: str
    description: str
    status: str
    source: str | None = None
    method: str | None = None


class MapSoundingStation(BaseModel):
    wmo_id: str = Field(pattern=r"^\d{5}$")
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    priority: int = 100


class WeatherMapDomain(BaseModel):
    west: float
    east: float
    south: float
    north: float
    resolution_degrees: float
    projection: str


class WeatherMapConfig(BaseModel):
    version: str
    region: str
    cycles: list[str]
    domain: WeatherMapDomain
    base_map: dict[str, object | None]
    input_pipeline: dict[str, object]
    analysis_method: dict[str, object]
    layers: list[WeatherMapLayer]
    climatology: dict[str, object] = Field(default_factory=dict)
    overlays: list[WeatherMapOverlay] = Field(default_factory=list)
    sounding_stations_file: str | None = None
    sounding_stations: list[MapSoundingStation] = Field(
        default_factory=list
    )


class WeatherMapProduct(BaseModel):
    layer_id: str
    valid_at: datetime
    generated_at: datetime
    source: str
    image_url: str
    metadata_url: str | None = None


class WeatherMapPreview(BaseModel):
    layer_id: str
    valid_at: datetime
    generated_at: datetime
    source: str
    image_url: str
    metadata_url: str
    publication_status: Literal["development-preview"] = (
        "development-preview"
    )
    base_map_status: Literal[
        "not-included",
        "official-boundary-preview",
        "official-service-preview",
    ] = "not-included"


class CycloneMarker(BaseModel):
    id: str
    kind: Literal["tropical", "low-pressure", "high-pressure"]
    valid_at: datetime
    latitude: float
    longitude: float
    name: str | None = None
    central_pressure_hpa: float | None = None
    central_height_dam: float | None = None
    maximum_wind_kt: float | None = None
    maximum_wind_ms: float | None = None
    source: str
    confidence: Literal["low", "medium", "high"] = "medium"


class SynopticFeature(BaseModel):
    """One objectively diagnosed front, trough axis, or ridge axis."""

    id: str
    kind: Literal[
        "cold-front",
        "warm-front",
        "stationary-front",
        "trough-axis",
        "ridge-axis",
    ]
    valid_at: datetime
    coordinates: list[tuple[float, float]] = Field(min_length=2)
    pressure_hpa: int | None = None
    confidence: Literal["medium", "high"] = "medium"
    score: float = Field(ge=0)
    source: str


class WeatherMapJob(BaseModel):
    layer_id: str
    label: str
    valid_at: datetime
    status: str
    blockers: list[str]
    recipe: dict[str, object]


class WeatherMapInputRequest(BaseModel):
    id: str
    source: str
    model: str
    resolution: str
    valid_date: date
    cycle: Literal["00", "12"]
    stream: str
    data_type: str
    step_hours: int
    format: Literal["grib2", "bufr"]
    levtype: str | None = None
    levelist: list[int] = Field(default_factory=list)
    parameters: list[str] = Field(default_factory=list)
    area: list[float] = Field(default_factory=list)
    grid: str | None = None
    target_path: str
    required: bool = True
    purposes: list[str] = Field(default_factory=list)
    status: Literal["archived", "missing"]


class WeatherMapPlan(BaseModel):
    valid_at: datetime
    domain: WeatherMapDomain
    requests: list[WeatherMapInputRequest]
    archived_inputs: int
    missing_required_inputs: list[str]
    blockers: list[str]
    status: Literal[
        "waiting-input",
        "waiting-compliant-base-map",
        "ready-for-analysis",
    ]
