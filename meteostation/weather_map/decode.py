from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from .fields import WeatherGrid
from .models import WeatherMapDomain


STANDARD_GRAVITY_MS2 = 9.80665


class WeatherMapDecodeUnavailable(RuntimeError):
    """Raised when an optional GRIB decoder is not installed."""


def decode_ecmwf_background(
    *,
    surface_path: Path,
    pressure_path: Path,
    valid_at: datetime,
    domain: WeatherMapDomain,
    forecast_step_hours: int = 0,
    initialized_at: datetime | None = None,
    precipitation_path: Path | None = None,
) -> WeatherGrid:
    """Decode planned ECMWF GRIB files into the normalized field schema."""
    try:
        import cfgrib
    except ImportError as exc:
        raise WeatherMapDecodeUnavailable(
            "缺少 cfgrib/eccodes；请安装 requirements-weather-map.txt。"
        ) from exc

    datasets = [
        *cfgrib.open_datasets(str(surface_path)),
        *cfgrib.open_datasets(str(pressure_path)),
    ]
    longitude, latitude = find_coordinates(datasets)
    fields: dict[str, np.ndarray] = {}
    precipitation_metadata = None
    if precipitation_path and precipitation_path.is_file():
        try:
            rain_datasets = cfgrib.open_datasets(str(precipitation_path), backend_kwargs={"read_keys":["startStep","endStep","stepType"]})
        except Exception:
            # Precipitation is optional. A corrupt or unverifiable GRIB must
            # fall back to 2-m temperature without blocking the whole chart.
            rain_datasets = []
        for rain_dataset in rain_datasets:
            if "tp" not in rain_dataset:
                continue
            rain = rain_dataset["tp"]
            start = rain.attrs.get("GRIB_startStep")
            end = rain.attrs.get("GRIB_endStep")
            # Display only an explicitly known accumulation interval and grid.
            if (rain.attrs.get("GRIB_stepType") == "accum" and rain.attrs.get("units") == "m"
                and rain.attrs.get("GRIB_stepUnits") == 1 and start is not None
                and end is not None and float(end) == forecast_step_hours and float(end) > float(start)
                and np.datetime64(valid_at.replace(tzinfo=None)) == rain_dataset.valid_time.values
                and np.array_equal(rain_dataset.longitude.values, longitude)
                and np.array_equal(rain_dataset.latitude.values, latitude)):
                values = np.asarray(rain.values, dtype=float).squeeze() * 1000
                if np.isfinite(values).all() and np.min(values) >= -0.01 and np.max(values) <= 3000:
                    fields["precipitation_accumulation_mm"] = np.maximum(values, 0)
                    precipitation_metadata = {"start_step":float(start),"end_step":float(end),"hours":float(end)-float(start),"source":"IFS model accumulation, not observed rainfall"}
    copy_surface_field(
        datasets,
        fields,
        target="mslp_hpa",
        aliases=("msl",),
        transform=lambda values: values / 100,
    )
    copy_surface_field(
        datasets,
        fields,
        target="surface_pressure_hpa",
        aliases=("sp",),
        transform=lambda values: values / 100,
        required=False,
    )
    copy_surface_field(
        datasets,
        fields,
        target="temperature_2m_c",
        aliases=("t2m", "2t"),
        transform=lambda values: values - 273.15,
    )
    copy_surface_field(
        datasets,
        fields,
        target="wind_u_10m_ms",
        aliases=("u10", "10u"),
    )
    copy_surface_field(
        datasets,
        fields,
        target="wind_v_10m_ms",
        aliases=("v10", "10v"),
    )
    copy_surface_field(
        datasets,
        fields,
        target="total_column_water_vapour_kg_m2",
        aliases=("tcwv",),
    )
    for pressure_hpa in (850, 500, 200):
        suffix = str(pressure_hpa)
        copy_pressure_field(
            datasets,
            fields,
            target=f"geopotential_height_{suffix}_gpm",
            aliases=("gh", "z"),
            pressure_hpa=pressure_hpa,
            transform=geopotential_to_height_if_needed,
        )
        copy_pressure_field(
            datasets,
            fields,
            target=f"temperature_{suffix}_c",
            aliases=("t",),
            pressure_hpa=pressure_hpa,
            transform=lambda values: values - 273.15,
        )
        copy_pressure_field(
            datasets,
            fields,
            target=f"relative_humidity_{suffix}_pct",
            aliases=("r",),
            pressure_hpa=pressure_hpa,
        )
        copy_pressure_field(
            datasets,
            fields,
            target=f"wind_u_{suffix}_ms",
            aliases=("u",),
            pressure_hpa=pressure_hpa,
        )
        copy_pressure_field(
            datasets,
            fields,
            target=f"wind_v_{suffix}_ms",
            aliases=("v",),
            pressure_hpa=pressure_hpa,
        )
        copy_pressure_field(
            datasets,
            fields,
            target=f"vorticity_{suffix}_s1",
            aliases=("vo",),
            pressure_hpa=pressure_hpa,
            required=False,
        )
        copy_pressure_field(
            datasets,
            fields,
            target=f"divergence_{suffix}_s1",
            aliases=("d",),
            pressure_hpa=pressure_hpa,
            required=False,
        )

    longitude, latitude, fields = normalize_coordinate_order(
        longitude,
        latitude,
        fields,
    )
    source = "ECMWF Open Data IFS 0.25°"
    if initialized_at is not None:
        source += (
            f" · {initialized_at:%Y-%m-%d %H UTC}"
            f" +{forecast_step_hours} h"
        )
    else:
        source += f" step {forecast_step_hours}"
    return WeatherGrid(
        valid_at=valid_at,
        source=source,
        longitude=longitude,
        latitude=latitude,
        fields=fields,
        metadata={
            "surface_file": str(surface_path),
            "pressure_file": str(pressure_path),
            "forecast_step_hours": forecast_step_hours,
            "initialized_at": (
                initialized_at.isoformat()
                if initialized_at is not None
                else None
            ),
            "license": "CC BY 4.0",
            "precipitation": precipitation_metadata,
        },
    ).subset(domain)


def find_coordinates(datasets: list[object]) -> tuple[np.ndarray, np.ndarray]:
    for dataset in datasets:
        if "longitude" in dataset.coords and "latitude" in dataset.coords:
            return (
                np.asarray(dataset.longitude.values, dtype=float),
                np.asarray(dataset.latitude.values, dtype=float),
            )
    raise ValueError("No latitude/longitude coordinates found in GRIB")


def copy_surface_field(
    datasets: list[object],
    fields: dict[str, np.ndarray],
    *,
    target: str,
    aliases: tuple[str, ...],
    transform: object | None = None,
    required: bool = True,
) -> None:
    values = find_data_values(datasets, aliases=aliases)
    if values is None:
        if required:
            raise ValueError(f"Required ECMWF field is missing: {target}")
        return
    fields[target] = transform(values) if transform else values


def copy_pressure_field(
    datasets: list[object],
    fields: dict[str, np.ndarray],
    *,
    target: str,
    aliases: tuple[str, ...],
    pressure_hpa: int,
    transform: object | None = None,
    required: bool = True,
) -> None:
    values = find_data_values(
        datasets,
        aliases=aliases,
        pressure_hpa=pressure_hpa,
    )
    if values is None:
        if required:
            raise ValueError(f"Required ECMWF field is missing: {target}")
        return
    fields[target] = transform(values) if transform else values


def find_data_values(
    datasets: list[object],
    *,
    aliases: tuple[str, ...],
    pressure_hpa: int | None = None,
) -> np.ndarray | None:
    for dataset in datasets:
        for alias in aliases:
            if alias not in dataset.data_vars:
                continue
            data = dataset[alias]
            if pressure_hpa is not None:
                pressure_coordinate = next(
                    (
                        name
                        for name in (
                            "isobaricInhPa",
                            "pressure_level",
                            "level",
                        )
                        if name in data.coords
                    ),
                    None,
                )
                if pressure_coordinate is None:
                    continue
                try:
                    data = data.sel({pressure_coordinate: pressure_hpa})
                except (KeyError, ValueError):
                    continue
            values = np.asarray(data.values, dtype=float).squeeze()
            if values.ndim == 2:
                if alias == "z":
                    values = values / STANDARD_GRAVITY_MS2
                return values
    return None


def geopotential_to_height_if_needed(values: np.ndarray) -> np.ndarray:
    """Normalize ECMWF ``gh`` or ``z`` to geopotential metres.

    ECMWF ``gh`` is already expressed in geopotential metres. Older or
    alternate ``z`` messages contain geopotential in m2 s-2 and therefore
    require division by standard gravity. Their magnitudes are separated by
    roughly one order, so the threshold remains safe for the pressure levels
    used by this project.
    """
    if np.nanmedian(np.abs(values)) > 20_000:
        return values / STANDARD_GRAVITY_MS2
    return values


def normalize_coordinate_order(
    longitude: np.ndarray,
    latitude: np.ndarray,
    fields: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    longitude = np.mod(longitude, 360)
    longitude_order = np.argsort(longitude)
    latitude_order = np.argsort(latitude)
    return (
        longitude[longitude_order],
        latitude[latitude_order],
        {
            name: values[np.ix_(latitude_order, longitude_order)]
            for name, values in fields.items()
        },
    )
