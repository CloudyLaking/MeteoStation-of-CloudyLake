from datetime import date, datetime

from pydantic import BaseModel, Field


class SurfaceObservation(BaseModel):
    observed_at: datetime
    temperature_c: float | None = None
    dewpoint_c: float | None = None
    relative_humidity_pct: float | None = Field(default=None, ge=0, le=100)
    station_pressure_hpa: float | None = Field(default=None, gt=0)
    wind_direction_deg: float | None = Field(default=None, ge=0, le=360)
    wind_speed_ms: float | None = Field(default=None, ge=0)
    gust_speed_ms: float | None = Field(default=None, ge=0)
    precipitation_1h_mm: float | None = Field(default=None, ge=0)
    visibility_km: float | None = Field(default=None, ge=0)


class SurfaceObservationSeries(BaseModel):
    station_id: str = Field(pattern=r"^\d{5}$")
    station_name: str
    station_name_en: str
    latitude: float
    longitude: float
    elevation_m: float
    observation_date: date
    source: str
    source_url: str
    fetched_at: datetime
    cache_status: str
    observations: list[SurfaceObservation]


class RealtimeObservation(BaseModel):
    station_id: str = Field(pattern=r"^\d{5}$")
    source: str
    source_url: str
    temperature_c: float | None = None
    relative_humidity_pct: float | None = Field(default=None, ge=0, le=100)
    station_pressure_hpa: float | None = Field(default=None, gt=0)
    wind_direction_deg: float | None = Field(default=None, ge=0, le=360)
    wind_speed_ms: float | None = Field(default=None, ge=0)
    precipitation_1h_mm: float | None = Field(default=None, ge=0)
    visibility_km: float | None = Field(default=None, ge=0)
    observed_at: datetime | None = None
