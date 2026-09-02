"""Weather-map configuration and saved-product catalog."""

from .analysis import (
    detect_height_axes,
    detect_low_pressure_centres,
    detect_high_pressure_centres,
    detect_pressure_level_centres,
    detect_surface_fronts,
    merge_cyclone_markers,
    smooth_field,
)
from .basemap import (
    LocalBoundaryLayer,
    TiandituBasemap,
    TiandituBasemapUnavailable,
    build_tianditu_wmts_url,
    load_geojson_boundary,
    load_tianditu_basemap,
)
from .catalog import WeatherMapCatalog
from .climatology import (
    HeightClimatology,
    HeightClimatologyUnavailable,
    TemperatureClimatology,
    load_era5_height_climatology,
    load_era5_temperature_climatology,
    retrieve_era5_height_climatology,
    retrieve_era5_temperature_climatology,
)
from .cyclones import (
    JtwcCycloneUnavailable,
    NmcCycloneUnavailable,
    NrlCycloneUnavailable,
    fetch_jtwc_tropical_cyclones,
    fetch_nmc_tropical_cyclones,
    fetch_nrl_tropical_cyclones,
    load_archived_nrl_tropical_cyclones,
    parse_jtwc_bdeck,
    parse_nmc_typhoon,
    parse_nrl_warning,
)
from .decode import WeatherMapDecodeUnavailable, decode_ecmwf_background
from .ecmwf import (
    EcmwfOpenDataUnavailable,
    EcmwfProductNotAvailable,
    retrieve_ecmwf_input,
)
from .fields import WeatherGrid
from .models import (
    CycloneMarker,
    SynopticFeature,
    WeatherMapConfig,
    WeatherMapDomain,
    WeatherMapInputRequest,
    WeatherMapJob,
    WeatherMapLayer,
    WeatherMapOverlay,
    WeatherMapPlan,
    WeatherMapPreview,
    WeatherMapProduct,
)
from .planner import build_weather_map_plan
from .preview import read_preview_catalog, update_preview_catalog
from .render import render_weather_map_preview

__all__ = [
    "WeatherMapCatalog",
    "CycloneMarker",
    "SynopticFeature",
    "HeightClimatology",
    "HeightClimatologyUnavailable",
    "TemperatureClimatology",
    "LocalBoundaryLayer",
    "TiandituBasemap",
    "TiandituBasemapUnavailable",
    "JtwcCycloneUnavailable",
    "NrlCycloneUnavailable",
    "WeatherMapConfig",
    "WeatherMapDomain",
    "WeatherMapInputRequest",
    "WeatherMapJob",
    "WeatherMapLayer",
    "WeatherMapOverlay",
    "WeatherMapPlan",
    "WeatherMapPreview",
    "WeatherMapProduct",
    "WeatherGrid",
    "WeatherMapDecodeUnavailable",
    "EcmwfOpenDataUnavailable",
    "EcmwfProductNotAvailable",
    "build_weather_map_plan",
    "build_tianditu_wmts_url",
    "load_geojson_boundary",
    "load_era5_height_climatology",
    "load_era5_temperature_climatology",
    "load_tianditu_basemap",
    "decode_ecmwf_background",
    "detect_height_axes",
    "detect_low_pressure_centres",
    "detect_high_pressure_centres",
    "detect_pressure_level_centres",
    "detect_surface_fronts",
    "fetch_jtwc_tropical_cyclones",
    "fetch_nrl_tropical_cyclones",
    "fetch_nmc_tropical_cyclones",
    "NmcCycloneUnavailable",
    "load_archived_nrl_tropical_cyclones",
    "parse_jtwc_bdeck",
    "parse_nmc_typhoon",
    "merge_cyclone_markers",
    "parse_nrl_warning",
    "read_preview_catalog",
    "render_weather_map_preview",
    "retrieve_ecmwf_input",
    "retrieve_era5_height_climatology",
    "retrieve_era5_temperature_climatology",
    "smooth_field",
    "update_preview_catalog",
]
