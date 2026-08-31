from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SoundingLevel(BaseModel):
    observed_at: datetime
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    pressure_hpa: float = Field(gt=0, le=1100)
    geopotential_height_m: float | None = None
    temperature_c: float | None = None
    dewpoint_c: float | None = None
    ice_point_c: float | None = None
    relative_humidity_pct: float | None = Field(default=None, ge=0, le=110)
    humidity_wrt_ice_pct: float | None = Field(default=None, ge=0, le=150)
    mixing_ratio_g_kg: float | None = Field(default=None, ge=0)
    wind_direction_deg: float | None = Field(default=None, ge=0, le=360)
    wind_speed_ms: float | None = Field(default=None, ge=0)


class SoundingProfile(BaseModel):
    station_id: str = Field(pattern=r"^\d{5}$")
    valid_at: datetime
    source: str
    source_url: str
    fetched_at: datetime
    cache_status: str
    level_count: int = Field(ge=1)
    surface_pressure_hpa: float
    top_pressure_hpa: float
    station_longitude: float
    station_latitude: float
    levels: list[SoundingLevel]


class SoundingProduct(BaseModel):
    station_id: str = Field(pattern=r"^\d{5}$")
    station_name: str | None = None
    valid_at: datetime
    source: str
    generated_at: datetime
    renderer_version: str
    diagram_type: Literal["skewt", "stuve"]
    level_count: int = Field(ge=1)
    image_path: str
    image_url: str


class ThermodynamicDiagnosticLevel(BaseModel):
    pressure_hpa: float = Field(gt=0, le=1100)
    virtual_temperature_c: float
    wet_bulb_temperature_c: float
    parcel_temperature_c: float
    equivalent_potential_temperature_k: float


class SoundingStructure(BaseModel):
    kind: Literal["inversion", "moist_layer", "dry_layer", "low_level_jet", "tropopause"]
    label: str
    bottom_pressure_hpa: float
    top_pressure_hpa: float
    bottom_height_agl_m: float | None = None
    top_height_agl_m: float | None = None
    strength: float | None = None
    confidence: Literal["高", "中", "低"]
    summary: str


class SoundingDiagnostics(BaseModel):
    station_id: str = Field(pattern=r"^\d{5}$")
    valid_at: datetime
    surface_based: bool = True
    lcl_pressure_hpa: float | None = None
    lcl_temperature_c: float | None = None
    lfc_pressure_hpa: float | None = None
    equilibrium_level_pressure_hpa: float | None = None
    cape_j_kg: float | None = None
    cin_j_kg: float | None = None
    mixed_layer_cape_j_kg: float | None = None
    mixed_layer_cin_j_kg: float | None = None
    most_unstable_cape_j_kg: float | None = None
    most_unstable_cin_j_kg: float | None = None
    dcape_j_kg: float | None = None
    precipitable_water_mm: float | None = None
    lifted_index_c: float | None = None
    k_index_c: float | None = None
    total_totals_index: float | None = None
    sweat_index: float | None = None
    lcl_height_agl_m: float | None = None
    lfc_height_agl_m: float | None = None
    equilibrium_level_height_agl_m: float | None = None
    freezing_level_pressure_hpa: float | None = None
    freezing_level_height_m: float | None = None
    bulk_shear_0_1km_ms: float | None = None
    bulk_shear_0_3km_ms: float | None = None
    bulk_shear_0_6km_ms: float | None = None
    storm_relative_helicity_0_1km_m2_s2: float | None = None
    storm_relative_helicity_0_3km_m2_s2: float | None = None
    bunkers_right_motion_u_ms: float | None = None
    bunkers_right_motion_v_ms: float | None = None
    bunkers_left_motion_u_ms: float | None = None
    bunkers_left_motion_v_ms: float | None = None
    mean_wind_0_6km_u_ms: float | None = None
    mean_wind_0_6km_v_ms: float | None = None
    critical_angle_deg: float | None = None
    significant_tornado_fixed: float | None = None
    lapse_rate_700_500_c_km: float | None = None
    structures: list[SoundingStructure] = Field(default_factory=list)
    levels: list[ThermodynamicDiagnosticLevel]


class SoundingCorrectionInput(BaseModel):
    pressure_hpa: float = Field(ge=100, le=1100)
    temperature_c: float = Field(ge=-100, le=65)
    dewpoint_c: float = Field(ge=-120, le=65)
    source_label: str = Field(default="manual", min_length=1, max_length=80)


class CorrectedSounding(BaseModel):
    profile: SoundingProfile
    diagnostics: SoundingDiagnostics
    correction: SoundingCorrectionInput
