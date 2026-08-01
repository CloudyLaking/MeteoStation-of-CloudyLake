from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import xarray as xr


GRAVITY_MS2 = 9.80665


class HeightClimatologyUnavailable(RuntimeError):
    """Raised when the configured 500 hPa climatology cannot be used."""


@dataclass(frozen=True)
class HeightClimatology:
    values_gpm: np.ndarray
    source: str
    normal_period: str
    month: int
    path: str


def retrieve_era5_height_climatology(
    target_path: Path,
    *,
    pressure_hpa: int = 500,
    start_year: int = 1991,
    end_year: int = 2020,
    month: int,
    west: float,
    east: float,
    south: float,
    north: float,
) -> Path:
    """Retrieve one calendar-month ERA5 height normal from the CDS."""
    try:
        import cdsapi
    except ImportError as exc:
        raise HeightClimatologyUnavailable(
            "cdsapi is required to retrieve the ERA5 climatology"
        ) from exc
    path = Path(target_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".download")
    request = {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": ["geopotential"],
        "pressure_level": [str(pressure_hpa)],
        "year": [str(year) for year in range(start_year, end_year + 1)],
        "month": [f"{month:02d}"],
        "time": ["00:00"],
        "area": [north, west, south, east],
        "data_format": "netcdf",
        "download_format": "unarchived",
    }
    try:
        cdsapi.Client().retrieve(
            "reanalysis-era5-pressure-levels-monthly-means",
            request,
            str(temporary),
        )
    except Exception as exc:
        if temporary.exists():
            temporary.unlink()
        raise HeightClimatologyUnavailable(
            f"ERA5 climatology retrieval failed: {exc}"
        ) from exc
    os.replace(temporary, path)
    metadata_path = path.with_suffix(path.suffix + ".json")
    metadata_path.write_text(
        json.dumps(
            {
                "source": "Copernicus Climate Data Store ERA5",
                "dataset": "reanalysis-era5-pressure-levels-monthly-means",
                "normal_period": f"{start_year}-{end_year}",
                "pressure_hpa": pressure_hpa,
                "month": month,
                "time": "00:00 UTC",
                "area": [north, west, south, east],
                "request": request,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def load_era5_height_climatology(
    path: Path,
    *,
    longitude: np.ndarray,
    latitude: np.ndarray,
    month: int,
    pressure_hpa: int = 500,
    normal_period: str = "1991-2020",
) -> HeightClimatology:
    """Load, average and interpolate an ERA5 monthly height normal."""
    source_path = Path(path)
    if not source_path.is_file():
        raise HeightClimatologyUnavailable(
            f"ERA5 climatology file is missing: {source_path}"
        )
    try:
        with xr.open_dataset(source_path) as dataset:
            field = _select_geopotential(dataset, pressure_hpa)
            time_name = next(
                (
                    name
                    for name in ("valid_time", "time", "date")
                    if name in field.coords
                ),
                None,
            )
            if time_name is not None:
                month_values = field[time_name].dt.month
                field = field.sel(
                    {time_name: field[time_name][month_values == month]}
                )
                if field.sizes.get(time_name, 0) == 0:
                    raise HeightClimatologyUnavailable(
                        f"No month {month:02d} values in {source_path}"
                    )
                field = field.mean(time_name, skipna=True)
            field = _collapse_non_spatial_dimensions(field)
            longitude_name = _coordinate_name(
                field,
                ("longitude", "lon"),
            )
            latitude_name = _coordinate_name(
                field,
                ("latitude", "lat"),
            )
            field = field.assign_coords(
                {
                    longitude_name: (
                        (
                            field[longitude_name] + 180
                        )
                        % 360
                    )
                    - 180
                }
            ).sortby(longitude_name)
            field = field.sortby(latitude_name)
            interpolated = field.interp(
                {
                    longitude_name: xr.DataArray(
                        np.asarray(longitude, dtype=float),
                        dims=("target_longitude",),
                    ),
                    latitude_name: xr.DataArray(
                        np.asarray(latitude, dtype=float),
                        dims=("target_latitude",),
                    ),
                },
                method="linear",
            )
            values = np.asarray(interpolated.values, dtype=float).squeeze()
    except HeightClimatologyUnavailable:
        raise
    except Exception as exc:
        raise HeightClimatologyUnavailable(
            f"Cannot read ERA5 climatology {source_path}: {exc}"
        ) from exc
    expected_shape = (len(latitude), len(longitude))
    if values.shape != expected_shape:
        if values.shape == expected_shape[::-1]:
            values = values.T
        else:
            raise HeightClimatologyUnavailable(
                f"ERA5 climatology has shape {values.shape}; "
                f"expected {expected_shape}"
            )
    finite_median = float(np.nanmedian(np.abs(values)))
    if finite_median > 20_000:
        values = values / GRAVITY_MS2
    if not np.isfinite(values).any():
        raise HeightClimatologyUnavailable(
            "ERA5 climatology contains no finite values in the map domain"
        )
    return HeightClimatology(
        values_gpm=values,
        source="Copernicus Climate Data Store ERA5 monthly mean",
        normal_period=normal_period,
        month=month,
        path=str(source_path),
    )


def _select_geopotential(
    dataset: xr.Dataset,
    pressure_hpa: int,
) -> xr.DataArray:
    for name in ("z", "geopotential"):
        if name in dataset.data_vars:
            field = dataset[name]
            break
    else:
        raise HeightClimatologyUnavailable(
            "ERA5 climatology has no geopotential variable"
        )
    for level_name in (
        "pressure_level",
        "isobaricInhPa",
        "level",
    ):
        if level_name not in field.coords:
            continue
        field = field.sel({level_name: pressure_hpa}, method="nearest")
        break
    return field


def _coordinate_name(
    field: xr.DataArray,
    candidates: tuple[str, ...],
) -> str:
    for name in candidates:
        if name in field.coords:
            return name
    raise HeightClimatologyUnavailable(
        f"Missing coordinate; expected one of {candidates}"
    )


def _collapse_non_spatial_dimensions(
    field: xr.DataArray,
) -> xr.DataArray:
    spatial = {"longitude", "lon", "latitude", "lat"}
    for dimension in tuple(field.dims):
        if dimension in spatial:
            continue
        field = field.mean(dimension, skipna=True)
    return field
