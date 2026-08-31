"""Transient ERA5 regional queries for the interactive reanalysis page."""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr


class ReanalysisUnavailable(RuntimeError):
    """Raised when CDS retrieval or ERA5 decoding fails."""


@dataclass(frozen=True)
class ReanalysisField:
    dataset: str
    variables: tuple[str, ...]
    candidates: tuple[str, ...]
    label: str
    unit: str
    level_required: bool = False


FIELDS: dict[str, ReanalysisField] = {
    "temperature_2m": ReanalysisField(
        "reanalysis-era5-single-levels",
        ("2m_temperature",),
        ("t2m", "2m_temperature"),
        "2 米气温",
        "°C",
    ),
    "mean_sea_level_pressure": ReanalysisField(
        "reanalysis-era5-single-levels",
        ("mean_sea_level_pressure",),
        ("msl", "mean_sea_level_pressure"),
        "海平面气压",
        "hPa",
    ),
    "cape": ReanalysisField(
        "reanalysis-era5-single-levels",
        ("convective_available_potential_energy",),
        ("cape", "convective_available_potential_energy"),
        "对流有效位能",
        "J/kg",
    ),
    "temperature": ReanalysisField(
        "reanalysis-era5-pressure-levels",
        ("temperature",),
        ("t", "temperature"),
        "等压面气温",
        "°C",
        True,
    ),
    "relative_humidity": ReanalysisField(
        "reanalysis-era5-pressure-levels",
        ("relative_humidity",),
        ("r", "relative_humidity"),
        "等压面相对湿度",
        "%",
        True,
    ),
    "geopotential_height": ReanalysisField(
        "reanalysis-era5-pressure-levels",
        ("geopotential",),
        ("z", "geopotential"),
        "位势高度",
        "gpm",
        True,
    ),
    "wind_speed": ReanalysisField(
        "reanalysis-era5-pressure-levels",
        ("u_component_of_wind", "v_component_of_wind"),
        ("u", "v"),
        "风速",
        "m/s",
        True,
    ),
}


def adapt_reanalysis_bounds(
    west: float,
    east: float,
    south: float,
    north: float,
    *,
    grid_step: float = 0.25,
    maximum_longitude_span: float = 120.0,
    maximum_latitude_span: float = 75.0,
    minimum_span: float = 0.5,
) -> tuple[float, float, float, float]:
    """Fit an arbitrary map viewport to a valid ERA5 request rectangle.

    Leaflet view bounds may cross the antimeridian or exceed the legal CDS
    domain after aspect-ratio padding.  Preserve the viewport centre, constrain
    its spans, and snap outward to the native quarter-degree ERA5 grid.
    """
    coordinates = np.asarray([west, east, south, north], dtype=float)
    if not np.all(np.isfinite(coordinates)):
        raise ValueError("reanalysis bounds must be finite")

    raw_longitude_span = east - west
    if raw_longitude_span <= 0:
        raw_longitude_span %= 360.0
    if raw_longitude_span <= 0 or raw_longitude_span > 360:
        raw_longitude_span = 360.0
    longitude_span = min(
        maximum_longitude_span,
        max(minimum_span, raw_longitude_span),
    )
    longitude_centre = ((west + raw_longitude_span / 2 + 180) % 360) - 180
    longitude_centre = float(np.clip(
        longitude_centre,
        -180 + longitude_span / 2,
        180 - longitude_span / 2,
    ))

    if north < south:
        south, north = north, south
    latitude_centre = float(np.clip((south + north) / 2, -90, 90))
    latitude_span = min(
        maximum_latitude_span,
        max(minimum_span, north - south),
    )
    latitude_centre = float(np.clip(
        latitude_centre,
        -90 + latitude_span / 2,
        90 - latitude_span / 2,
    ))

    fitted_west = longitude_centre - longitude_span / 2
    fitted_east = longitude_centre + longitude_span / 2
    fitted_south = latitude_centre - latitude_span / 2
    fitted_north = latitude_centre + latitude_span / 2

    fitted_west = np.floor(fitted_west / grid_step) * grid_step
    fitted_east = np.ceil(fitted_east / grid_step) * grid_step
    fitted_south = np.floor(fitted_south / grid_step) * grid_step
    fitted_north = np.ceil(fitted_north / grid_step) * grid_step

    # Outward grid snapping can add at most one grid interval. Re-constrain
    # the far edge while keeping every boundary on the native grid.
    if fitted_east - fitted_west > maximum_longitude_span:
        fitted_east = fitted_west + maximum_longitude_span
    if fitted_north - fitted_south > maximum_latitude_span:
        fitted_north = fitted_south + maximum_latitude_span
    if fitted_east > 180:
        fitted_west -= fitted_east - 180
        fitted_east = 180.0
    if fitted_west < -180:
        fitted_east += -180 - fitted_west
        fitted_west = -180.0
    if fitted_north > 90:
        fitted_south -= fitted_north - 90
        fitted_north = 90.0
    if fitted_south < -90:
        fitted_north += -90 - fitted_south
        fitted_south = -90.0

    return tuple(
        round(float(value), 2)
        for value in (fitted_west, fitted_east, fitted_south, fitted_north)
    )


def retrieve_reanalysis_grid(
    *,
    valid_at: datetime,
    field_id: str,
    pressure_hpa: int | None,
    north: float,
    west: float,
    south: float,
    east: float,
) -> dict[str, object]:
    """Retrieve one ERA5 time/field/area and return a compact JSON grid."""
    specification = FIELDS.get(field_id)
    if specification is None:
        raise ReanalysisUnavailable(f"Unsupported ERA5 field: {field_id}")
    if specification.level_required and pressure_hpa is None:
        raise ReanalysisUnavailable("A pressure level is required for this field")
    try:
        import cdsapi
    except ImportError as exc:
        raise ReanalysisUnavailable("CDS API client is not installed") from exc

    request: dict[str, object] = {
        "product_type": ["reanalysis"],
        "variable": list(specification.variables),
        "year": [f"{valid_at.year:04d}"],
        "month": [f"{valid_at.month:02d}"],
        "day": [f"{valid_at.day:02d}"],
        "time": [f"{valid_at.hour:02d}:00"],
        "area": [north, west, south, east],
        "data_format": "netcdf",
        "download_format": "unarchived",
    }
    if specification.level_required:
        request["pressure_level"] = [str(pressure_hpa)]

    with tempfile.TemporaryDirectory(prefix="cloudylake-era5-") as temporary:
        target = Path(temporary) / "era5.nc"
        try:
            cdsapi.Client(quiet=True).retrieve(
                specification.dataset,
                request,
                str(target),
            )
        except Exception as exc:
            raise ReanalysisUnavailable(f"ERA5 query failed: {exc}") from exc
        source = _unwrap_download(target)
        try:
            with xr.open_dataset(source) as dataset:
                longitude_name = _coordinate_name(dataset, ("longitude", "lon"))
                latitude_name = _coordinate_name(dataset, ("latitude", "lat"))
                longitude = np.asarray(dataset[longitude_name].values, dtype=float)
                latitude = np.asarray(dataset[latitude_name].values, dtype=float)
                values = _field_values(dataset, specification, field_id)
                wind_components = None
                if field_id == "wind_speed":
                    wind_components = (
                        _data_array(dataset, ("u", "u_component_of_wind")),
                        _data_array(dataset, ("v", "v_component_of_wind")),
                    )
        except Exception as exc:
            raise ReanalysisUnavailable(f"Cannot decode ERA5 response: {exc}") from exc

    values = np.asarray(values, dtype=float).squeeze()
    if values.ndim != 2:
        raise ReanalysisUnavailable(f"Unexpected ERA5 grid shape: {values.shape}")
    if longitude.ndim != 1 or latitude.ndim != 1:
        raise ReanalysisUnavailable("ERA5 coordinates are not a regular latitude/longitude grid")
    if latitude[0] > latitude[-1]:
        latitude = latitude[::-1]
        values = values[::-1, :]
        if wind_components is not None:
            wind_components = (wind_components[0][::-1, :], wind_components[1][::-1, :])
    if longitude[0] > longitude[-1]:
        longitude = longitude[::-1]
        values = values[:, ::-1]
        if wind_components is not None:
            wind_components = (wind_components[0][:, ::-1], wind_components[1][:, ::-1])
    if wind_components is not None and np.asarray(wind_components[0]).shape != values.shape:
        wind_components = None

    # Keep browser responses fast even for the largest permitted query box.
    latitude_stride = max(1, int(np.ceil(latitude.size / 181)))
    longitude_stride = max(1, int(np.ceil(longitude.size / 281)))
    latitude = latitude[::latitude_stride]
    longitude = longitude[::longitude_stride]
    values = values[::latitude_stride, ::longitude_stride]
    if wind_components is not None:
        wind_components = (
            np.asarray(wind_components[0])[::latitude_stride, ::longitude_stride],
            np.asarray(wind_components[1])[::latitude_stride, ::longitude_stride],
        )
    finite = values[np.isfinite(values)]
    if not finite.size:
        raise ReanalysisUnavailable("ERA5 returned no finite values for this area")
    rounded_values = [
        [round(float(value), 3) if np.isfinite(value) else None for value in row]
        for row in values
    ]
    result = {
        "valid_at": valid_at.astimezone(timezone.utc).isoformat(),
        "field_id": field_id,
        "field_label": specification.label,
        "unit": specification.unit,
        "pressure_hpa": pressure_hpa if specification.level_required else None,
        "longitude": [round(float(value), 4) for value in longitude],
        "latitude": [round(float(value), 4) for value in latitude],
        "values": rounded_values,
        "minimum": round(float(np.nanmin(values)), 3),
        "maximum": round(float(np.nanmax(values)), 3),
        "source": "Copernicus Climate Data Store · ERA5 hourly reanalysis",
        "temporary_query": True,
    }
    if wind_components is not None:
        result["u_wind"] = [[round(float(value), 2) for value in row] for row in wind_components[0]]
        result["v_wind"] = [[round(float(value), 2) for value in row] for row in wind_components[1]]
    return result


def _unwrap_download(target: Path) -> Path:
    if not zipfile.is_zipfile(target):
        return target
    directory = target.parent / "unzipped"
    directory.mkdir()
    with zipfile.ZipFile(target) as archive:
        archive.extractall(directory)
    candidates = list(directory.glob("*.nc"))
    if not candidates:
        shutil.rmtree(directory, ignore_errors=True)
        raise ReanalysisUnavailable("CDS returned an archive without a NetCDF file")
    return candidates[0]


def _coordinate_name(dataset: xr.Dataset, candidates: tuple[str, ...]) -> str:
    for name in candidates:
        if name in dataset.coords:
            return name
    raise ReanalysisUnavailable(f"Missing coordinate: {'/'.join(candidates)}")


def _data_array(dataset: xr.Dataset, candidates: tuple[str, ...]) -> np.ndarray:
    for name in candidates:
        if name in dataset.data_vars:
            array = dataset[name]
            for dimension in tuple(array.dims):
                if dimension not in {"latitude", "lat", "longitude", "lon"}:
                    array = array.isel({dimension: 0})
            return np.asarray(array.values, dtype=float)
    raise ReanalysisUnavailable(f"Missing variable: {'/'.join(candidates)}")


def _field_values(
    dataset: xr.Dataset,
    specification: ReanalysisField,
    field_id: str,
) -> np.ndarray:
    if field_id == "wind_speed":
        u_wind = _data_array(dataset, ("u", "u_component_of_wind"))
        v_wind = _data_array(dataset, ("v", "v_component_of_wind"))
        return np.hypot(u_wind, v_wind)
    values = _data_array(dataset, specification.candidates)
    if field_id in {"temperature", "temperature_2m"}:
        return values - 273.15 if np.nanmedian(values) > 150 else values
    if field_id == "mean_sea_level_pressure":
        return values / 100 if np.nanmedian(values) > 2000 else values
    if field_id == "geopotential_height":
        return values / 9.80665 if np.nanmedian(values) > 20000 else values
    return values
