"""Chunked forecast store optimized for arbitrary single-grid-point reads."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np

from .models import (
    ForecastSounding,
    ForecastSoundingLevel,
    SurfaceForecast,
    SurfaceForecastPoint,
)


StoreKind = Literal["surface", "pressure"]

_SURFACE_NAMES = {
    "10u": "u10",
    "10v": "v10",
    "2t": "t2m",
    "2d": "d2m",
    "sp": "sp",
    "msl": "msl",
    "tp": "tp",
    "tcc": "tcc",
}
_PRESSURE_NAMES = {name: name for name in ("gh", "t", "r", "q", "u", "v")}
_SPATIAL_CHUNK = 128
_DECIMAL_PRECISION = {
    "10u": 2,
    "10v": 2,
    "2t": 2,
    "2d": 2,
    "sp": 0,
    "msl": 0,
    "tp": 5,
    "tcc": 3,
    "gh": 1,
    "t": 2,
    "r": 1,
    "q": 7,
    "u": 2,
    "v": 2,
}


def fast_store_path(grib_path: Path) -> Path:
    """Return the adjacent derived-store path for a forecast GRIB."""
    path = Path(grib_path)
    if path.name.endswith(".grib2"):
        return path.with_name(f"{path.name[:-6]}.fast.nc")
    return path.with_suffix(".fast.nc")


def is_fast_store(path: Path) -> bool:
    return Path(path).name.endswith(".fast.nc")


def convert_forecast_grib(
    grib_path: Path,
    *,
    kind: StoreKind,
) -> Path:
    """Stream one global GRIB into an atomic, point-query-friendly NetCDF4.

    Surface fields are chunked across multiple forecast steps because the
    normal query is a time series. Pressure fields keep one step per chunk
    because the normal query is one vertical profile. Both layouts use small
    spatial tiles, avoiding a scan of the global field for every request.
    """
    source = Path(grib_path)
    if is_fast_store(source):
        validate_fast_store(source, kind=kind)
        return source
    target = fast_store_path(source)
    if target.exists():
        validate_fast_store(target, kind=kind)
        return target

    try:
        import cfgrib
        from netCDF4 import Dataset
    except ImportError as exc:  # pragma: no cover - deployment dependency
        raise RuntimeError("cfgrib and netCDF4 are required for conversion") from exc

    datasets = cfgrib.open_datasets(str(source))
    fields = _forecast_fields(datasets, kind=kind)
    if not fields:
        raise RuntimeError(f"no {kind} forecast fields found in {source.name}")

    first = next(iter(fields.values()))
    latitude = np.asarray(first.coords["latitude"].values, dtype=np.float32)
    longitude = np.asarray(first.coords["longitude"].values, dtype=np.float32)
    steps = sorted(
        {
            step
            for field in fields.values()
            for step in _field_step_hours(field)
        }
    )
    if not steps:
        raise RuntimeError(f"no forecast steps found in {source.name}")

    levels: list[float] = []
    if kind == "pressure":
        levels = sorted(
            {
                float(level)
                for field in fields.values()
                for level in np.atleast_1d(
                    field.coords["isobaricInhPa"].values
                )
            },
            reverse=True,
        )
        if not levels:
            raise RuntimeError(f"no pressure levels found in {source.name}")

    temporary = target.with_suffix(f"{target.suffix}.part")
    temporary.unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Dataset(temporary, "w", format="NETCDF4") as store:
            store.setncattr("store_format", "meteostation-point-v1")
            store.setncattr("source_grib", source.name)
            store.setncattr("kind", kind)
            store.createDimension("step", len(steps))
            store.createDimension("latitude", len(latitude))
            store.createDimension("longitude", len(longitude))
            if levels:
                store.createDimension("isobaricInhPa", len(levels))

            store.createVariable("step", "i2", ("step",))[:] = steps
            store.createVariable("latitude", "f4", ("latitude",))[:] = latitude
            store.createVariable("longitude", "f4", ("longitude",))[:] = longitude
            if levels:
                store.createVariable(
                    "isobaricInhPa", "f4", ("isobaricInhPa",)
                )[:] = levels

            step_lookup = {value: index for index, value in enumerate(steps)}
            level_lookup = {value: index for index, value in enumerate(levels)}
            for short_name, field in fields.items():
                stored_name = (_SURFACE_NAMES if kind == "surface" else _PRESSURE_NAMES)[
                    short_name
                ]
                if kind == "surface":
                    dimensions = ("step", "latitude", "longitude")
                    chunks = (
                        min(16, len(steps)),
                        min(_SPATIAL_CHUNK, len(latitude)),
                        min(_SPATIAL_CHUNK, len(longitude)),
                    )
                else:
                    dimensions = (
                        "step",
                        "isobaricInhPa",
                        "latitude",
                        "longitude",
                    )
                    chunks = (
                        1,
                        len(levels),
                        min(_SPATIAL_CHUNK, len(latitude)),
                        min(_SPATIAL_CHUNK, len(longitude)),
                    )
                variable = store.createVariable(
                    stored_name,
                    "f4",
                    dimensions,
                    zlib=True,
                    complevel=4,
                    shuffle=True,
                    chunksizes=chunks,
                    fill_value=np.float32(np.nan),
                    least_significant_digit=_DECIMAL_PRECISION[short_name],
                )
                variable.setncattr("GRIB_shortName", short_name)
                _write_field(
                    variable,
                    field,
                    kind=kind,
                    step_lookup=step_lookup,
                    level_lookup=level_lookup,
                )
        validate_fast_store(temporary, kind=kind)
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def validate_fast_store(path: Path, *, kind: StoreKind) -> None:
    """Fail fast when an interrupted or incompatible store is encountered."""
    from netCDF4 import Dataset

    with Dataset(path, "r") as store:
        if store.getncattr("store_format") != "meteostation-point-v1":
            raise RuntimeError(f"unsupported fast-store format: {path}")
        if store.getncattr("kind") != kind:
            raise RuntimeError(f"wrong fast-store kind: {path}")
        required = {"step", "latitude", "longitude"}
        if kind == "pressure":
            required.add("isobaricInhPa")
        if not required.issubset(store.variables):
            raise RuntimeError(f"incomplete fast store: {path}")


def read_fast_point_fields(
    path: Path,
    *,
    latitude: float,
    longitude: float,
    step_hours: int | None = None,
) -> dict[str, Any]:
    """Read only the spatial chunks touching the nearest requested point."""
    import xarray as xr
    from netCDF4 import Dataset

    fields: dict[str, Any] = {}
    with Dataset(path, "r") as store:
        latitudes = np.asarray(store.variables["latitude"][:])
        longitudes = np.asarray(store.variables["longitude"][:])
        steps = np.asarray(store.variables["step"][:], dtype=int)
        lat_index = int(np.argmin(np.abs(latitudes - latitude)))
        lon_index = int(np.argmin(np.abs(longitudes - (longitude % 360))))
        selected_step_indices: slice | list[int] = slice(None)
        selected_steps = steps
        if step_hours is not None:
            matches = np.flatnonzero(steps == step_hours)
            if not len(matches):
                return {}
            selected_step_indices = [int(matches[0])]
            selected_steps = steps[selected_step_indices]

        levels = (
            np.asarray(store.variables["isobaricInhPa"][:], dtype=float)
            if "isobaricInhPa" in store.variables
            else None
        )
        coordinates: dict[str, Any] = {"step": selected_steps}
        if levels is not None:
            coordinates["isobaricInhPa"] = levels
        coordinate_names = {"step", "latitude", "longitude", "isobaricInhPa"}
        for stored_name, variable in store.variables.items():
            if stored_name in coordinate_names:
                continue
            short_name = str(getattr(variable, "GRIB_shortName", stored_name)).lower()
            if levels is None:
                values = np.asarray(
                    variable[selected_step_indices, lat_index, lon_index]
                )
                dimensions = ("step",)
            else:
                values = np.asarray(
                    variable[
                        selected_step_indices,
                        slice(None),
                        lat_index,
                        lon_index,
                    ]
                )
                dimensions = ("step", "isobaricInhPa")
            fields[short_name] = xr.DataArray(
                values,
                dims=dimensions,
                coords=coordinates,
                attrs={"GRIB_shortName": short_name},
            )
    return fields


def _forecast_fields(datasets: list[Any], *, kind: StoreKind) -> dict[str, Any]:
    allowed = _SURFACE_NAMES if kind == "surface" else _PRESSURE_NAMES
    fields: dict[str, Any] = {}
    for dataset in datasets:
        if "latitude" not in dataset.coords or "longitude" not in dataset.coords:
            continue
        for variable_name, field in dataset.data_vars.items():
            short_name = str(field.attrs.get("GRIB_shortName", variable_name)).lower()
            if short_name in allowed:
                fields[short_name] = field
    return fields


def _field_step_hours(field: Any) -> list[int]:
    if "step" not in field.coords:
        return [0]
    raw = np.atleast_1d(np.asarray(field.coords["step"].values))
    if np.issubdtype(raw.dtype, np.timedelta64):
        return [int(round(float(value / np.timedelta64(1, "h")))) for value in raw]
    return [int(round(float(value))) for value in raw]


def _write_field(
    target: Any,
    field: Any,
    *,
    kind: StoreKind,
    step_lookup: dict[int, int],
    level_lookup: dict[float, int],
) -> None:
    steps = _field_step_hours(field)
    if "step" not in field.dims:
        field = field.expand_dims("step")
    if kind == "surface":
        values = np.asarray(
            field.transpose("step", "latitude", "longitude").values,
            dtype=np.float32,
        )
        target_indices = [step_lookup[step] for step in steps]
        if target_indices == list(range(len(step_lookup))):
            # One sequential assignment lets HDF5 compress each multi-step
            # chunk exactly once. Writing one step at a time repeatedly
            # recompresses the same chunk and is an order of magnitude slower.
            target[:, :, :] = values
        else:
            for source_step_index, target_step_index in enumerate(target_indices):
                target[target_step_index, :, :] = values[source_step_index]
        return
    for source_step_index, step in enumerate(steps):
        step_field = field.isel(step=source_step_index)
        target_step_index = step_lookup[step]
        source_levels = [
            float(value)
            for value in np.atleast_1d(step_field.coords["isobaricInhPa"].values)
        ]
        values = np.asarray(
            step_field.transpose("isobaricInhPa", "latitude", "longitude").values,
            dtype=np.float32,
        )
        for source_level_index, level in enumerate(source_levels):
            target[
                target_step_index,
                level_lookup[level],
                :,
                :,
            ] = values[source_level_index]


def extract_surface_forecast_fast(
    path: Path,
    *,
    station_id: str,
    station_name: str,
    latitude: float,
    longitude: float,
    initialized_at: datetime,
) -> SurfaceForecast:
    """Read a complete point time series without decoding global fields."""
    from netCDF4 import Dataset

    with Dataset(path, "r") as store:
        store.set_auto_mask(False)
        lat_index, lon_index = _nearest_grid_indices(store, latitude, longitude)
        steps = [int(value) for value in store.variables["step"][:]]
        values = {
            name: np.asarray(variable[:, lat_index, lon_index], dtype=float)
            for name, variable in store.variables.items()
            if name in set(_SURFACE_NAMES.values())
        }

    points: list[SurfaceForecastPoint] = []
    previous_total_precip_mm: float | None = None
    for index, step in enumerate(steps):
        t2m = _value_at(values, "t2m", index)
        d2m = _value_at(values, "d2m", index)
        u10 = _value_at(values, "u10", index)
        v10 = _value_at(values, "v10", index)
        surface_pressure = _value_at(values, "sp", index)
        msl = _value_at(values, "msl", index)
        total_precip = _value_at(values, "tp", index)
        cloud_cover = _value_at(values, "tcc", index)
        temperature_c = t2m - 273.15 if t2m is not None else None
        dewpoint_c = d2m - 273.15 if d2m is not None else None
        accumulated_precip_mm = (
            total_precip * 1000.0 if total_precip is not None else None
        )
        precipitation_mm = None
        if accumulated_precip_mm is not None:
            precipitation_mm = max(
                accumulated_precip_mm - (previous_total_precip_mm or 0.0),
                0.0,
            )
            previous_total_precip_mm = accumulated_precip_mm
        humidity = None
        if temperature_c is not None and dewpoint_c is not None:
            a, b = 17.27, 237.7
            humidity = float(
                100.0
                * np.exp(
                    a * dewpoint_c / (b + dewpoint_c)
                    - a * temperature_c / (b + temperature_c)
                )
            )
        wind_speed, wind_direction = _wind(u10, v10)
        cloud_pct = None
        if cloud_cover is not None:
            cloud_pct = cloud_cover * 100.0 if abs(cloud_cover) <= 1.5 else cloud_cover
            cloud_pct = float(np.clip(cloud_pct, 0.0, 100.0))
        points.append(
            SurfaceForecastPoint(
                valid_at=initialized_at + timedelta(hours=step),
                step_hours=step,
                temperature_2m_c=_rounded(temperature_c, 1),
                dewpoint_2m_c=_rounded(dewpoint_c, 1),
                relative_humidity_2m_pct=_rounded(humidity, 0),
                wind_speed_10m_ms=_rounded(wind_speed, 1),
                wind_direction_10m_deg=_rounded(wind_direction, 0),
                mslp_hpa=_rounded(msl / 100.0 if msl is not None else None, 1),
                surface_pressure_hpa=_rounded(
                    surface_pressure / 100.0
                    if surface_pressure is not None
                    else None,
                    1,
                ),
                total_precipitation_mm=_rounded(precipitation_mm, 1),
                total_cloud_cover_pct=_rounded(cloud_pct, 0),
            )
        )
    return SurfaceForecast(
        station_id=station_id,
        station_name=station_name,
        latitude=latitude,
        longitude=longitude,
        initialized_at=initialized_at,
        source=f"{_source_name(path)} 0.25° · {initialized_at:%Y-%m-%d %H} UTC",
        points=points,
    )


def extract_sounding_forecast_fast(
    path: Path,
    *,
    station_id: str,
    station_name: str,
    latitude: float,
    longitude: float,
    initialized_at: datetime,
    step_hours: int,
) -> list[ForecastSounding]:
    """Read one point/step profile from the derived chunked store."""
    from netCDF4 import Dataset

    with Dataset(path, "r") as store:
        store.set_auto_mask(False)
        steps = [int(value) for value in store.variables["step"][:]]
        if step_hours not in steps:
            return []
        step_index = steps.index(step_hours)
        lat_index, lon_index = _nearest_grid_indices(store, latitude, longitude)
        levels = [float(value) for value in store.variables["isobaricInhPa"][:]]
        values = {
            name: np.asarray(
                variable[step_index, :, lat_index, lon_index],
                dtype=float,
            )
            for name, variable in store.variables.items()
            if name in _PRESSURE_NAMES
        }

    sounding_levels: list[ForecastSoundingLevel] = []
    for index, pressure_hpa in enumerate(levels):
        height = _value_at(values, "gh", index)
        temperature_k = _value_at(values, "t", index)
        relative_humidity = _value_at(values, "r", index)
        specific_humidity = _value_at(values, "q", index)
        u_wind = _value_at(values, "u", index)
        v_wind = _value_at(values, "v", index)
        temperature_c = (
            temperature_k - 273.15 if temperature_k is not None else None
        )
        if (
            relative_humidity is None
            and specific_humidity is not None
            and temperature_c is not None
        ):
            epsilon = 0.621981
            vapour_pressure = specific_humidity * pressure_hpa / (
                epsilon + (1.0 - epsilon) * specific_humidity
            )
            saturation = 6.112 * np.exp(
                17.67 * temperature_c / (temperature_c + 243.5)
            )
            relative_humidity = float(
                np.clip(100.0 * vapour_pressure / saturation, 0.0, 100.0)
            )
        dewpoint_c = None
        if temperature_c is not None and relative_humidity is not None:
            a, b = 17.27, 237.7
            bounded = float(np.clip(relative_humidity, 1e-3, 100.0))
            gamma = np.log(bounded / 100.0) + a * temperature_c / (
                b + temperature_c
            )
            dewpoint_c = b * gamma / (a - gamma)
        wind_speed, wind_direction = _wind(u_wind, v_wind)
        sounding_levels.append(
            ForecastSoundingLevel(
                pressure_hpa=pressure_hpa,
                height_gpm=_rounded(height, 1),
                temperature_c=_rounded(temperature_c, 1),
                dewpoint_c=_rounded(dewpoint_c, 1),
                relative_humidity_pct=_rounded(relative_humidity, 1),
                wind_direction_deg=_rounded(wind_direction, 0),
                wind_speed_ms=_rounded(wind_speed, 1),
            )
        )
    return [
        ForecastSounding(
            station_id=station_id,
            station_name=station_name,
            latitude=latitude,
            longitude=longitude,
            valid_at=initialized_at + timedelta(hours=step_hours),
            step_hours=step_hours,
            initialized_at=initialized_at,
            source=(
                f"{_source_name(path)} 0.25° · "
                f"{initialized_at:%Y-%m-%d %H} UTC +{step_hours}h"
            ),
            levels=sounding_levels,
        )
    ]


def _nearest_grid_indices(store: Any, latitude: float, longitude: float) -> tuple[int, int]:
    latitudes = np.asarray(store.variables["latitude"][:], dtype=float)
    longitudes = np.asarray(store.variables["longitude"][:], dtype=float)
    return (
        int(np.argmin(np.abs(latitudes - latitude))),
        int(np.argmin(np.abs(longitudes - (longitude % 360.0)))),
    )


def _value_at(values: dict[str, np.ndarray], name: str, index: int) -> float | None:
    if name not in values:
        return None
    value = float(values[name][index])
    return value if np.isfinite(value) else None


def _rounded(value: float | None, digits: int) -> float | None:
    return round(float(value), digits) if value is not None and np.isfinite(value) else None


def _wind(u: float | None, v: float | None) -> tuple[float | None, float | None]:
    if u is None or v is None:
        return None, None
    return float(np.hypot(u, v)), float(np.degrees(np.arctan2(-u, -v)) % 360)


def _source_name(path: Path) -> str:
    model = "AIFS" if Path(path).name.casefold().startswith("aifs_") else "IFS"
    return f"ECMWF Open Data {model}"
