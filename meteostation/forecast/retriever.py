"""ECMWF forecast retrieval and station-point extraction."""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
from ecmwf.opendata import Client as EcmwfClient
from multiurl import download as multiurl_download

from meteostation.ecmwf_mars import (
    MarsAccessUnavailable,
    MarsClientUnavailable,
    mars_model_keywords,
    mars_point_area,
    retrieve_mars,
)

from .models import (
    ForecastSounding,
    ForecastSoundingLevel,
    SurfaceForecast,
    SurfaceForecastPoint,
)
from .fast_store import (
    fast_store_has_pressure_levels,
    fast_store_path,
    is_fast_store,
    read_fast_point_fields,
)

_log = logging.getLogger(__name__)

# Pressure levels used for forecast soundings.
FORECAST_PRESSURE_LEVELS = [
    1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50,
]

# Surface forecast parameters.
SURFACE_PARAMS = ["2t", "2d", "10u", "10v", "sp", "msl", "tp", "tcc"]

# Pressure-level forecast parameters. AIFS Open Data publishes specific
# humidity (q), rather than relative humidity (r), on pressure levels.
IFS_PRESSURE_PARAMS = ["gh", "t", "r", "u", "v"]
AIFS_PRESSURE_PARAMS = ["gh", "t", "q", "u", "v"]

FORECAST_HORIZON_HOURS = 144


def forecast_step_hours(model: str) -> list[int]:
    """Return the native Open Data steps retained for one model cycle."""
    cadence = 6 if model.casefold() == "aifs" else 3
    return list(range(0, FORECAST_HORIZON_HOURS + 1, cadence))


def pressure_parameters(model: str) -> list[str]:
    """Return pressure-level fields available for the requested model."""
    if model.casefold() == "aifs":
        return AIFS_PRESSURE_PARAMS
    return IFS_PRESSURE_PARAMS


def _nearest_index(
    target: float,
    grid: np.ndarray,
) -> int:
    """Return the index of the nearest grid point."""
    return int(np.argmin(np.abs(grid - target)))


def _dewpoint_from_rh(
    temperature_c: np.ndarray,
    relative_humidity_pct: np.ndarray,
) -> np.ndarray:
    """Estimate dewpoint from temperature and relative humidity (Magnus formula)."""
    a, b = 17.27, 237.7
    gamma = a * temperature_c / (b + temperature_c) + np.log(
        np.clip(relative_humidity_pct / 100.0, 1e-6, 1.0)
    )
    return b * gamma / (a - gamma)


def _wind_dir_speed(
    u: np.ndarray,
    v: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute meteorological wind direction and speed from U/V components."""
    speed = np.hypot(u, v)
    direction = np.degrees(np.arctan2(-u, -v)) % 360
    return direction, speed


def retrieve_ecmwf_forecast(
    *,
    initialized_at: datetime,
    cache_root: Path,
    model: str = "ifs",
    source: str = "ecmwf",
    resolution: str = "0p25",
    include_surface: bool = True,
    include_pressure: bool = True,
    latitude: float | None = None,
    longitude: float | None = None,
    backend: str | None = None,
    allow_download: bool = True,
    cached_step: int | None = None,
) -> tuple[Path, Path]:
    """Download surface and pressure-level forecast GRIB files.

    Returns (surface_path, pressure_path).
    """
    selected_backend = (
        backend or os.getenv("ECMWF_FORECAST_BACKEND", "open-data")
    ).casefold()
    if (
        selected_backend in {"auto", "mars"}
        and latitude is not None
        and longitude is not None
    ):
        try:
            return _retrieve_mars_point_forecast(
                initialized_at=initialized_at,
                cache_root=cache_root,
                model=model,
                latitude=latitude,
                longitude=longitude,
                include_surface=include_surface,
                include_pressure=include_pressure,
            )
        except (MarsAccessUnavailable, MarsClientUnavailable):
            if selected_backend == "mars":
                raise
            _log.warning(
                "MARS is unavailable; retaining the ECMWF Open Data fallback"
            )

    client_model = "aifs-single" if model == "aifs" else model
    client = EcmwfClient(
        source=source,
        model=client_model,
        resol=resolution,
    )
    cache_dir = (
        cache_root
        / "ecmwf_forecast"
        / model
        / f"{initialized_at:%Y}"
        / f"{initialized_at:%m}"
        / f"{initialized_at:%d}"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)

    stem = f"{model}_{initialized_at:%Y%m%d}_{initialized_at:%H}z"

    request_base: dict[str, object] = {
        "date": initialized_at.strftime("%Y-%m-%d"),
        "time": initialized_at.hour,
        "type": "fc",
    }

    # ---- surface -----------------------------------------------------------
    cadence = 6 if model == "aifs" else 3
    steps = forecast_step_hours(model)
    surf_path = (
        cache_dir
        / f"{stem}_forecast_surface_144h_{cadence}hourly.grib2"
    )
    surface_store = fast_store_path(surf_path)
    if include_surface and surface_store.exists():
        surf_path = surface_store
    if include_surface and not allow_download and not surf_path.exists():
        partial = _find_partial_step_cache(
            cache_dir,
            stem=stem,
            field_type="surface",
            step=cached_step,
        )
        if partial is None:
            raise FileNotFoundError(
                f"{model.upper()} {initialized_at:%Y-%m-%d %H} UTC "
                "surface cycle is not cached yet"
            )
        surf_path = partial
    if include_surface and not surf_path.exists():
        _log.info(
            "Downloading %s surface forecast (%s) → %s",
            model.upper(),
            initialized_at.strftime("%Y-%m-%d %HZ"),
            surf_path,
        )
        _retrieve_atomically(
            client,
            request={
                    **request_base,
                    "step": steps,
                    "levtype": "sfc",
                    "param": SURFACE_PARAMS,
            },
            target=surf_path,
        )

    # ---- pressure levels ---------------------------------------------------
    pres_path = (
        cache_dir
        / f"{stem}_forecast_pressure_144h_{cadence}hourly.grib2"
    )
    pressure_store = fast_store_path(pres_path)
    if pressure_store.exists() and not fast_store_has_pressure_levels(
        pressure_store,
        FORECAST_PRESSURE_LEVELS,
    ):
        # Native pressure-level coverage changed; rebuild this derived cache
        # instead of serving a permanently sparse forecast sounding.
        pressure_store.unlink()
    if include_pressure and pressure_store.exists():
        pres_path = pressure_store
    if include_pressure and not allow_download and not pres_path.exists():
        partial = _find_partial_step_cache(
            cache_dir,
            stem=stem,
            field_type="pressure",
            step=cached_step,
        )
        if partial is None:
            raise FileNotFoundError(
                f"{model.upper()} {initialized_at:%Y-%m-%d %H} UTC "
                "pressure cycle is not cached yet"
            )
        pres_path = partial
    if include_pressure and not pres_path.exists():
        _log.info(
            "Downloading %s pressure-level forecast (%s) → %s",
            model.upper(),
            initialized_at.strftime("%Y-%m-%d %HZ"),
            pres_path,
        )
        _retrieve_atomically(
            client,
            request={
                    **request_base,
                    "step": steps,
                    "levtype": "pl",
                    "levelist": FORECAST_PRESSURE_LEVELS,
                    "param": pressure_parameters(model),
            },
            target=pres_path,
        )

    # ---- housekeeping: remove caches older than 3 days --------------------
    _clean_old_forecast_caches(cache_root / "ecmwf_forecast", model)

    return surf_path, pres_path


def retrieve_ecmwf_forecast_step(
    *,
    initialized_at: datetime,
    step: int,
    cache_root: Path,
    model: str = "ifs",
    source: str = "aws",
) -> tuple[Path, Path]:
    """Download one forecast step as a small, explicitly partial demo cache."""
    if step not in forecast_step_hours(model):
        cadence = 6 if model.casefold() == "aifs" else 3
        raise ValueError(
            f"{model.upper()} step must be 0—144 h by {cadence} h"
        )

    client_model = "aifs-single" if model == "aifs" else model
    client = EcmwfClient(
        source=source,
        model=client_model,
        resol="0p25",
    )
    cache_dir = (
        Path(cache_root)
        / "ecmwf_forecast"
        / model
        / f"{initialized_at:%Y}"
        / f"{initialized_at:%m}"
        / f"{initialized_at:%d}"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{model}_{initialized_at:%Y%m%d}_{initialized_at:%H}z"
    request_base: dict[str, object] = {
        "date": initialized_at.strftime("%Y-%m-%d"),
        "time": initialized_at.hour,
        "type": "fc",
        "step": step,
    }
    surface_path = (
        cache_dir / f"{stem}_forecast_surface_step{step:03d}.grib2"
    )
    pressure_path = (
        cache_dir / f"{stem}_forecast_pressure_step{step:03d}.grib2"
    )
    if not surface_path.exists():
        _retrieve_atomically(
            client,
            request={
                **request_base,
                "levtype": "sfc",
                "param": SURFACE_PARAMS,
            },
            target=surface_path,
        )
    if not pressure_path.exists():
        _retrieve_atomically(
            client,
            request={
                **request_base,
                "levtype": "pl",
                "levelist": FORECAST_PRESSURE_LEVELS,
                "param": pressure_parameters(model),
            },
            target=pressure_path,
        )
    return surface_path, pressure_path


def _find_partial_step_cache(
    cache_dir: Path,
    *,
    stem: str,
    field_type: str,
    step: int | None,
) -> Path | None:
    if step is not None:
        candidate = (
            cache_dir
            / f"{stem}_forecast_{field_type}_step{step:03d}.grib2"
        )
        return candidate if candidate.exists() else None
    candidates = list(
        cache_dir.glob(f"{stem}_forecast_{field_type}_step*.grib2")
    )
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def _retrieve_mars_point_forecast(
    *,
    initialized_at: datetime,
    cache_root: Path,
    model: str,
    latitude: float,
    longitude: float,
    include_surface: bool,
    include_pressure: bool,
) -> tuple[Path, Path]:
    location = f"{latitude:.3f}_{longitude:.3f}".replace("-", "m")
    cache_dir = (
        cache_root
        / "ecmwf_forecast"
        / model
        / f"{initialized_at:%Y}"
        / f"{initialized_at:%m}"
        / f"{initialized_at:%d}"
        / location
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{model}_{initialized_at:%Y%m%d}_{initialized_at:%H}z"
    base_request: dict[str, object] = {
        **mars_model_keywords(model),
        "date": initialized_at.strftime("%Y-%m-%d"),
        "time": f"{initialized_at:%H}",
        "stream": "oper",
        "type": "fc",
        "grid": "0.25/0.25",
        "area": mars_point_area(latitude, longitude),
    }

    cadence = 6 if model == "aifs" else 3
    surface_path = (
        cache_dir / f"{stem}_surface_144h_{cadence}hourly_mars.grib2"
    )
    if include_surface and not surface_path.exists():
        retrieve_mars(
            {
                **base_request,
                "step": f"0/to/{FORECAST_HORIZON_HOURS}/by/{cadence}",
                "levtype": "sfc",
                "param": "/".join(SURFACE_PARAMS),
            },
            surface_path,
        )

    pressure_path = (
        cache_dir / f"{stem}_pressure_144h_{cadence}hourly_mars.grib2"
    )
    if include_pressure and not pressure_path.exists():
        retrieve_mars(
            {
                **base_request,
                "step": f"0/to/{FORECAST_HORIZON_HOURS}/by/{cadence}",
                "levtype": "pl",
                "levelist": "/".join(
                    str(level) for level in FORECAST_PRESSURE_LEVELS
                ),
                "param": "/".join(pressure_parameters(model)),
            },
            pressure_path,
        )

    _clean_old_forecast_caches(cache_root / "ecmwf_forecast", model)
    return surface_path, pressure_path


def _retrieve_atomically(
    client: EcmwfClient,
    *,
    request: dict[str, object],
    target: Path,
) -> None:
    """Download an indexed request atomically and resume interrupted ranges."""
    temporary = target.with_suffix(f"{target.suffix}.part")
    continuation = temporary.with_suffix(f"{temporary.suffix}.resume")

    # A killed process can leave the currently downloaded continuation behind.
    # It is still the exact next byte sequence in the selected GRIB stream, so
    # fold it into the durable partial before calculating the remaining ranges.
    if continuation.exists():
        temporary.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("ab") as destination, continuation.open("rb") as source:
            shutil.copyfileobj(source, destination)
        continuation.unlink()

    try:
        result = client._get_urls(
            request,
            target=str(temporary),
            use_index=True,
        )
        if client.use_sas_token:
            result.urls = client._apply_sas_to_urls(result.urls)

        expected_size = _indexed_download_size(result.urls)
        if expected_size is None:
            # All production forecast requests are index-backed. Keep a safe
            # fallback for a future source that does not return byte ranges.
            temporary.unlink(missing_ok=True)
            client.retrieve(request=request, target=str(temporary))
        else:
            existing_size = (
                temporary.stat().st_size
                if temporary.exists()
                else 0
            )
            if existing_size > expected_size:
                temporary.unlink()
                existing_size = 0

            remaining_urls = _trim_indexed_urls(
                result.urls,
                existing_size,
            )
            if remaining_urls:
                multiurl_download(
                    remaining_urls,
                    target=str(continuation),
                    verify=client.verify,
                    session=client.session,
                    accept_ranges=client.source.accept_ranges,
                    accept_multiple_ranges=(
                        client.source.accept_multiple_ranges
                    ),
                )
                with temporary.open("ab") as destination, continuation.open(
                    "rb"
                ) as source:
                    shutil.copyfileobj(source, destination)
                continuation.unlink()

            actual_size = (
                temporary.stat().st_size
                if temporary.exists()
                else 0
            )
            if actual_size != expected_size:
                raise RuntimeError(
                    "ECMWF partial size mismatch: "
                    f"{actual_size} != {expected_size}"
                )

        if not temporary.exists() or temporary.stat().st_size == 0:
            raise RuntimeError("ECMWF returned an empty GRIB file")
        temporary.replace(target)
    except Exception:
        # Preserve both files. On the next run the continuation is appended to
        # the main partial, and the remaining indexed byte ranges are trimmed.
        raise


def _indexed_download_size(urls: object) -> int | None:
    """Return concatenated selected-byte size, or ``None`` without ranges."""
    if not isinstance(urls, (list, tuple)):
        return None
    total = 0
    for item in urls:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            return None
        _, parts = item
        if parts is None:
            return None
        for part in parts:
            if not isinstance(part, (list, tuple)) or len(part) != 2:
                return None
            total += int(part[1])
    return total


def _trim_indexed_urls(
    urls: object,
    downloaded_bytes: int,
) -> list[tuple[str, tuple[tuple[int, int], ...]]]:
    """Remove already persisted bytes from ordered Open Data index ranges."""
    if downloaded_bytes < 0:
        raise ValueError("downloaded_bytes must not be negative")
    remaining_skip = downloaded_bytes
    trimmed: list[tuple[str, tuple[tuple[int, int], ...]]] = []
    if not isinstance(urls, (list, tuple)):
        raise ValueError("indexed URLs must be a sequence")

    for item in urls:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("indexed URL item must contain URL and ranges")
        url, parts = item
        if parts is None:
            raise ValueError("indexed URL item has no byte ranges")
        remaining_parts: list[tuple[int, int]] = []
        for offset, length in parts:
            offset = int(offset)
            length = int(length)
            if remaining_skip >= length:
                remaining_skip -= length
                continue
            if remaining_skip:
                offset += remaining_skip
                length -= remaining_skip
                remaining_skip = 0
            remaining_parts.append((offset, length))
        if remaining_parts:
            trimmed.append((str(url), tuple(remaining_parts)))

    if remaining_skip:
        raise ValueError("partial file is larger than the indexed selection")
    return trimmed


def _clean_old_forecast_caches(
    forecast_root: Path,
    model: str,
    *,
    keep_days: int = 3,
) -> None:
    """Remove per-model forecast GRIB directories older than *keep_days*."""
    model_root = forecast_root / model
    if not model_root.is_dir():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)

    for year_dir in model_root.iterdir():
        if not year_dir.is_dir():
            continue
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir():
                continue
            for day_dir in month_dir.iterdir():
                if not day_dir.is_dir():
                    continue
                try:
                    dir_date = datetime(
                        int(year_dir.name),
                        int(month_dir.name),
                        int(day_dir.name),
                        tzinfo=timezone.utc,
                    )
                except (ValueError, TypeError):
                    continue
                if dir_date < cutoff:
                    _log.debug("Removing expired forecast cache: %s", day_dir)
                    shutil.rmtree(day_dir, ignore_errors=True)


def extract_surface_forecast(
    surface_grib_path: Path,
    *,
    station_id: str,
    station_name: str,
    latitude: float,
    longitude: float,
    initialized_at: datetime,
) -> SurfaceForecast | None:
    """Extract surface forecast time series at a single station."""
    source_name = _forecast_source_name(surface_grib_path)
    if is_fast_store(surface_grib_path):
        fields = read_fast_point_fields(
            surface_grib_path,
            latitude=latitude,
            longitude=longitude,
        )
    else:
        try:
            import cfgrib
        except ImportError:
            _log.warning("cfgrib not available — cannot decode surface forecast")
            return None
        datasets = cfgrib.open_datasets(str(surface_grib_path))
        if not datasets:
            return None
        fields = _point_fields(datasets, latitude=latitude, longitude=longitude)
    wanted = ("10u", "10v", "2t", "2d", "sp", "msl", "tp", "tcc")
    series = {
        name: _surface_series(fields[name])
        for name in wanted
        if name in fields
    }
    steps = sorted({step for values in series.values() for step in values})
    if not steps or not series:
        return None

    def _at_point(name: str, step: int) -> float | None:
        return series.get(name, {}).get(step)

    points: list[SurfaceForecastPoint] = []
    previous_total_precip_mm: float | None = None
    for step in steps:
        t2m = _at_point("2t", step)
        d2m = _at_point("2d", step)
        u10 = _at_point("10u", step)
        v10 = _at_point("10v", step)
        sp = _at_point("sp", step)
        msl = _at_point("msl", step)
        tp = _at_point("tp", step)
        tcc = _at_point("tcc", step)

        temp_c = t2m - 273.15 if t2m is not None else None
        td_c = d2m - 273.15 if d2m is not None else None
        sp_hpa = sp / 100.0 if sp is not None else None
        mslp = msl / 100.0 if msl is not None else None
        accumulated_precip = tp * 1000.0 if tp is not None else None
        precip = None
        if accumulated_precip is not None:
            if previous_total_precip_mm is None:
                precip = max(accumulated_precip, 0.0)
            else:
                precip = max(
                    accumulated_precip - previous_total_precip_mm,
                    0.0,
                )
            previous_total_precip_mm = accumulated_precip
        cloud = None
        if tcc is not None:
            # IFS is commonly decoded as a 0—1 fraction while AIFS Open
            # Data may expose the same field directly in percent.
            cloud = tcc * 100.0 if abs(tcc) <= 1.5 else tcc
            cloud = float(np.clip(cloud, 0.0, 100.0))

        ws = None
        wd = None
        if u10 is not None and v10 is not None:
            direction, speed = _wind_dir_speed(
                np.asarray(u10),
                np.asarray(v10),
            )
            ws = float(speed)
            wd = float(direction)

        # Estimate RH from T and Td if Td is available.
        rh = None
        if temp_c is not None and td_c is not None:
            a, b = 17.27, 237.7
            rh = float(100.0 * np.exp(
                a * td_c / (b + td_c) - a * temp_c / (b + temp_c)
            ))

        points.append(
            SurfaceForecastPoint(
                valid_at=initialized_at + timedelta(hours=step),
                step_hours=step,
                temperature_2m_c=round(temp_c, 1) if temp_c is not None else None,
                dewpoint_2m_c=round(td_c, 1) if td_c is not None else None,
                relative_humidity_2m_pct=round(rh) if rh is not None else None,
                wind_speed_10m_ms=round(ws, 1) if ws is not None else None,
                wind_direction_10m_deg=round(wd) if wd is not None else None,
                mslp_hpa=round(mslp, 1) if mslp is not None else None,
                surface_pressure_hpa=round(sp_hpa, 1) if sp_hpa is not None else None,
                total_precipitation_mm=round(precip, 1) if precip is not None else None,
                total_cloud_cover_pct=round(cloud) if cloud is not None else None,
            )
        )

    return SurfaceForecast(
        station_id=station_id,
        station_name=station_name,
        latitude=latitude,
        longitude=longitude,
        initialized_at=initialized_at,
        source=(
            f"{source_name} 0.25° · "
            f"{initialized_at:%Y-%m-%d %H} UTC"
        ),
        points=points,
    )


def extract_sounding_forecast(
    pressure_grib_path: Path,
    *,
    station_id: str,
    station_name: str,
    latitude: float,
    longitude: float,
    initialized_at: datetime,
    step_hours: int | None = None,
) -> list[ForecastSounding] | None:
    """Extract vertical profile forecasts at one or all cached steps.

    Selecting *step_hours* before loading values is essential for full global
    cycle files: ecCodes otherwise decodes every global field for every step
    even though only one grid point is returned.
    """
    source_name = _forecast_source_name(pressure_grib_path)
    if is_fast_store(pressure_grib_path):
        fields = read_fast_point_fields(
            pressure_grib_path,
            latitude=latitude,
            longitude=longitude,
            step_hours=step_hours,
        )
    else:
        try:
            import cfgrib
        except ImportError:
            _log.warning("cfgrib not available — cannot decode pressure-level forecast")
            return None
        datasets = cfgrib.open_datasets(str(pressure_grib_path))
        if not datasets:
            return None
        fields = _point_fields(
            datasets,
            latitude=latitude,
            longitude=longitude,
            step_hours=step_hours,
        )
    profiles = {
        name: _pressure_series(fields[name])
        for name in ("gh", "t", "r", "q", "u", "v")
        if name in fields
    }
    steps = sorted(
        {step for values in profiles.values() for step, _ in values}
    )
    pressure_levels = sorted(
        {level for values in profiles.values() for _, level in values},
        reverse=True,
    )
    if not steps or not pressure_levels or not profiles:
        return None

    def _at_point(name: str, step: int, pressure: float) -> float | None:
        return profiles.get(name, {}).get((step, pressure))

    soundings: list[ForecastSounding] = []
    for step in steps:
        levels: list[ForecastSoundingLevel] = []
        for lev_hpa in pressure_levels:
            gh = _at_point("gh", step, lev_hpa)
            t_k = _at_point("t", step, lev_hpa)
            rh_pct = _at_point("r", step, lev_hpa)
            q = _at_point("q", step, lev_hpa)
            u = _at_point("u", step, lev_hpa)
            v = _at_point("v", step, lev_hpa)

            temp_c = t_k - 273.15 if t_k is not None else None
            height = gh  # ECMWF Open Data ``gh`` is already in gpm.
            if rh_pct is None and q is not None and temp_c is not None:
                # Convert specific humidity to RH using pressure-level
                # vapour pressure and the Magnus saturation curve.
                epsilon = 0.621981
                vapour_pressure_hpa = (
                    q * lev_hpa / (epsilon + (1.0 - epsilon) * q)
                )
                saturation_hpa = 6.112 * np.exp(
                    17.67 * temp_c / (temp_c + 243.5)
                )
                rh_pct = float(
                    np.clip(
                        100.0 * vapour_pressure_hpa / saturation_hpa,
                        0.0,
                        100.0,
                    )
                )
            ws = None
            wd = None
            if u is not None and v is not None:
                direction, speed = _wind_dir_speed(
                    np.asarray(u),
                    np.asarray(v),
                )
                ws = float(speed)
                wd = float(direction)

            # Compute dewpoint from T and RH.
            td = None
            if temp_c is not None and rh_pct is not None:
                a, b = 17.27, 237.7
                bounded_rh = float(np.clip(rh_pct, 1e-3, 100.0))
                gamma = np.log(bounded_rh / 100.0) + a * temp_c / (b + temp_c)
                td = round(float(b * gamma / (a - gamma)), 1)

            levels.append(
                ForecastSoundingLevel(
                    pressure_hpa=lev_hpa,
                    height_gpm=round(height, 1) if height is not None else None,
                    temperature_c=round(temp_c, 1) if temp_c is not None else None,
                    dewpoint_c=td,
                    relative_humidity_pct=round(rh_pct, 1) if rh_pct is not None else None,
                    wind_direction_deg=round(wd) if wd is not None else None,
                    wind_speed_ms=round(ws, 1) if ws is not None else None,
                )
            )
        soundings.append(
            ForecastSounding(
                station_id=station_id,
                station_name=station_name,
                latitude=latitude,
                longitude=longitude,
                valid_at=initialized_at + timedelta(hours=step),
                step_hours=step,
                initialized_at=initialized_at,
                source=(
                    f"{source_name} 0.25° · "
                    f"{initialized_at:%Y-%m-%d %H} UTC +{step}h"
                ),
                levels=levels,
            )
        )

    return soundings


def _forecast_source_name(path: Path) -> str:
    filename = Path(path).name.casefold()
    model = "AIFS" if filename.startswith("aifs_") else "IFS"
    access = "MARS" if "_mars" in filename else "Open Data"
    return f"ECMWF {access} {model}"


def _point_fields(
    datasets: list[Any],
    *,
    latitude: float,
    longitude: float,
    step_hours: int | None = None,
) -> dict[str, Any]:
    """Select the nearest model grid point before loading field values."""
    fields: dict[str, Any] = {}
    for dataset in datasets:
        if "latitude" not in dataset.coords or "longitude" not in dataset.coords:
            continue
        if step_hours is not None and "step" in dataset.coords:
            available_steps = _step_hours(dataset.coords["step"].values)
            if step_hours not in available_steps:
                continue
            if "step" in dataset.dims:
                dataset = dataset.isel(
                    step=available_steps.index(step_hours)
                )
            elif available_steps != [step_hours]:
                continue
        model_longitude = longitude % 360
        selected = dataset.sel(
            latitude=latitude,
            longitude=model_longitude,
            method="nearest",
        )
        for variable_name, data_array in selected.data_vars.items():
            short_name = str(
                data_array.attrs.get("GRIB_shortName", variable_name)
            ).lower()
            fields[short_name] = data_array.load()
    return fields


def _step_hours(values: Any) -> list[int]:
    raw = np.atleast_1d(np.asarray(values))
    if np.issubdtype(raw.dtype, np.timedelta64):
        return [
            int(round(float(value / np.timedelta64(1, "h"))))
            for value in raw
        ]
    return [int(round(float(value))) for value in raw]


def _finite_float(value: Any) -> float | None:
    if np.ma.is_masked(value):
        return None
    result = float(value)
    return result if np.isfinite(result) else None


def _surface_series(data_array: Any) -> dict[int, float | None]:
    values = np.atleast_1d(np.asarray(data_array.values))
    if "step" in data_array.coords:
        steps = _step_hours(data_array.coords["step"].values)
    else:
        steps = [0]
    return {
        step: _finite_float(value)
        for step, value in zip(steps, values, strict=True)
    }


def _pressure_series(
    data_array: Any,
) -> dict[tuple[int, float], float | None]:
    if "step" not in data_array.coords or "isobaricInhPa" not in data_array.coords:
        return {}
    ordered = data_array
    if "step" not in ordered.dims:
        # cfgrib squeezes a file containing one forecast step to a scalar
        # ``step`` coordinate. Promote it back to a dimension so the same
        # decoder handles both partial demonstrations and full cycles.
        ordered = ordered.expand_dims("step")
    ordered = ordered.transpose("step", "isobaricInhPa")
    steps = _step_hours(ordered.coords["step"].values)
    levels = [
        float(value)
        for value in np.atleast_1d(ordered.coords["isobaricInhPa"].values)
    ]
    values = np.asarray(ordered.values)
    return {
        (step, level): _finite_float(values[step_index, level_index])
        for step_index, step in enumerate(steps)
        for level_index, level in enumerate(levels)
    }
