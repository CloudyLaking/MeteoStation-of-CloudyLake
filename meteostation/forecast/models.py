"""Point forecast models for CloudyLake's Observatory.

Powered with Codex & Deepseek V4 Pro.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class SurfaceForecastPoint(BaseModel):
    """One forecast time-step for a single station."""

    valid_at: datetime
    step_hours: int
    temperature_2m_c: float | None = None
    dewpoint_2m_c: float | None = None
    relative_humidity_2m_pct: float | None = None
    wind_speed_10m_ms: float | None = None
    wind_direction_10m_deg: float | None = None
    mslp_hpa: float | None = None
    surface_pressure_hpa: float | None = None
    total_precipitation_mm: float | None = None
    total_cloud_cover_pct: float | None = None


class SurfaceForecast(BaseModel):
    """Multi-step surface forecast for a single station."""

    station_id: str
    station_name: str
    latitude: float
    longitude: float
    initialized_at: datetime
    source: str
    points: list[SurfaceForecastPoint]


class ForecastSoundingLevel(BaseModel):
    """One pressure level in an ECMWF forecast sounding."""

    pressure_hpa: float
    height_gpm: float | None = None
    temperature_c: float | None = None
    dewpoint_c: float | None = None
    relative_humidity_pct: float | None = None
    wind_direction_deg: float | None = None
    wind_speed_ms: float | None = None


class ForecastSounding(BaseModel):
    """ECMWF forecast vertical profile at one time step."""

    station_id: str
    station_name: str
    latitude: float
    longitude: float
    valid_at: datetime
    step_hours: int
    initialized_at: datetime
    source: str
    levels: list[ForecastSoundingLevel]
