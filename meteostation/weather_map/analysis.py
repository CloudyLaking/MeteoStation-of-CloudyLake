from __future__ import annotations

import logging
from collections.abc import Iterable

import numpy as np
from scipy.ndimage import gaussian_filter, maximum_filter, minimum_filter

from .fields import WeatherGrid
from .models import CycloneMarker, WeatherMapDomain

_log = logging.getLogger(__name__)


def smooth_field(
    values: np.ndarray,
    *,
    sigma_gridpoints: float,
) -> np.ndarray:
    """Apply a NaN-aware Gaussian filter for synoptic chart rendering."""
    array = np.asarray(values, dtype=float)
    if sigma_gridpoints <= 0:
        return array.copy()
    finite = np.isfinite(array)
    if not finite.any():
        return array.copy()
    weighted_values = gaussian_filter(
        np.where(finite, array, 0.0),
        sigma=sigma_gridpoints,
        mode="nearest",
    )
    weights = gaussian_filter(
        finite.astype(float),
        sigma=sigma_gridpoints,
        mode="nearest",
    )
    return np.divide(
        weighted_values,
        weights,
        out=np.full_like(weighted_values, np.nan),
        where=weights > 1e-6,
    )


def detect_low_pressure_centres(
    grid: WeatherGrid,
    *,
    domain: WeatherMapDomain,
    maximum_centres: int = 6,
) -> list[CycloneMarker]:
    """Locate well-separated synoptic MSLP minima north of 30°N.

    These are objective low-pressure centres, not an authoritative cyclone
    best-track product. Tropical cyclone identifiers are supplied separately.
    """
    subset = grid.subset(domain)
    pressure = smooth_field(
        subset.fields["mslp_hpa"],
        sigma_gridpoints=2.25,
    )
    grid_spacing = max(
        float(np.nanmedian(np.diff(subset.longitude))),
        float(np.nanmedian(np.diff(subset.latitude))),
    )
    neighbourhood = _odd_window(max(9, round(5.0 / grid_spacing)))
    ring_radius = max(5, round(3.0 / grid_spacing))
    local_minimum = minimum_filter(
        pressure,
        size=neighbourhood,
        mode="nearest",
    )
    candidates = np.argwhere(
        np.isfinite(pressure)
        & np.isclose(pressure, local_minimum, atol=0.02)
    )
    ranked: list[tuple[float, float, int, int]] = []
    for latitude_index, longitude_index in candidates:
        latitude = float(subset.latitude[latitude_index])
        if (
            latitude < 30.0
            or latitude > domain.north - 1.5
        ):
            continue
        centre_pressure = float(
            pressure[latitude_index, longitude_index]
        )
        if centre_pressure > 1006.0:
            continue
        depth = _surrounding_depth(
            pressure,
            latitude_index,
            longitude_index,
            ring_radius,
        )
        if not np.isfinite(depth) or depth < 2.5:
            continue
        ranked.append(
            (
                centre_pressure,
                -depth,
                int(latitude_index),
                int(longitude_index),
            )
        )

    markers: list[CycloneMarker] = []
    for centre_pressure, negative_depth, lat_index, lon_index in sorted(
        ranked
    ):
        latitude = float(subset.latitude[lat_index])
        longitude = float(subset.longitude[lon_index])
        if any(
            _angular_distance_degrees(
                latitude,
                longitude,
                marker.latitude,
                marker.longitude,
            )
            < 5.0
            for marker in markers
        ):
            continue
        markers.append(
            CycloneMarker(
                id=f"objective-low-{len(markers) + 1}",
                kind="low-pressure",
                valid_at=subset.valid_at,
                latitude=latitude,
                longitude=longitude,
                central_pressure_hpa=round(centre_pressure),
                source="Objective analysis of smoothed ECMWF MSLP",
                confidence=(
                    "high"
                    if -negative_depth >= 4
                    else "medium"
                ),
            )
        )
        if len(markers) >= maximum_centres:
            break
    return markers


def detect_high_pressure_centres(
    grid: WeatherGrid,
    *,
    domain: WeatherMapDomain,
    maximum_centres: int = 6,
) -> list[CycloneMarker]:
    """Locate prominent, well-separated MSLP maxima for H overlays.

    Uses latitude-dependent thresholds to handle both mid-latitude
    continental highs (typically >1016 hPa, sharper) and subtropical
    highs (typically 1010–1016 hPa, broader).  Masked grid points
    where ``surface_pressure_hpa < 850`` exclude high-terrain MSLP
    reduction artefacts (e.g. the Tibetan Plateau).
    """
    subset = grid.subset(domain)
    pressure = smooth_field(
        subset.fields["mslp_hpa"],
        sigma_gridpoints=2.25,
    )
    surface_pressure = subset.fields.get("surface_pressure_hpa")

    grid_spacing = max(
        float(np.nanmedian(np.diff(subset.longitude))),
        float(np.nanmedian(np.diff(subset.latitude))),
    )
    neighbourhood = _odd_window(max(9, round(5.0 / grid_spacing)))
    ring_radius = max(5, round(3.0 / grid_spacing))
    local_maximum = maximum_filter(
        pressure,
        size=neighbourhood,
        mode="nearest",
    )
    # ---- terrain mask: reject MSLP over high ground (> ~1500 m) ----------
    if surface_pressure is not None:
        terrain_mask = surface_pressure >= 850.0
    else:
        terrain_mask = np.ones_like(pressure, dtype=bool)

    candidates = np.argwhere(
        np.isfinite(pressure)
        & terrain_mask
        & np.isclose(pressure, local_maximum, atol=0.02)
    )
    total_candidates = len(candidates)

    ranked: list[tuple[float, float, int, int]] = []
    for latitude_index, longitude_index in candidates:
        latitude = float(subset.latitude[latitude_index])
        longitude = float(subset.longitude[longitude_index])
        if (
            latitude < domain.south + 1.5
            or latitude > domain.north - 1.5
            or longitude < domain.west + 1.5
            or longitude > domain.east - 1.5
        ):
            continue
        centre_pressure = float(
            pressure[latitude_index, longitude_index]
        )

        # Latitude-dependent thresholds.
        # Mid-latitude continental highs (≥ 35°N): sharper, higher pressure.
        # Subtropical high belt (15–35°N): broader, weaker at the surface.
        if latitude >= 35.0:
            min_pressure = 1014.0
            min_prominence = 2.5
        else:
            min_pressure = 1010.0
            min_prominence = 1.8

        if centre_pressure < min_pressure:
            continue
        prominence = _surrounding_depth(
            -pressure,
            latitude_index,
            longitude_index,
            ring_radius,
        )
        if not np.isfinite(prominence) or prominence < min_prominence:
            continue
        ranked.append(
            (
                -centre_pressure,
                -prominence,
                int(latitude_index),
                int(longitude_index),
            )
        )

    markers: list[CycloneMarker] = []
    for negative_pressure, negative_prominence, lat_index, lon_index in sorted(
        ranked
    ):
        latitude = float(subset.latitude[lat_index])
        longitude = float(subset.longitude[lon_index])
        if any(
            _angular_distance_degrees(
                latitude,
                longitude,
                marker.latitude,
                marker.longitude,
            )
            < 5.0
            for marker in markers
        ):
            continue
        centre_pressure = -negative_pressure
        prominence_value = -negative_prominence
        markers.append(
            CycloneMarker(
                id=f"objective-high-{len(markers) + 1}",
                kind="high-pressure",
                valid_at=subset.valid_at,
                latitude=latitude,
                longitude=longitude,
                central_pressure_hpa=round(centre_pressure),
                source="Objective analysis of smoothed ECMWF MSLP",
                confidence=(
                    "high"
                    if prominence_value >= 4.0
                    else "medium"
                ),
            )
        )
        if len(markers) >= maximum_centres:
            break

    _log.debug(
        "高压候选统计：原始局部极大 %d → 通过筛选 %d → 去重输出 %d",
        total_candidates,
        len(ranked),
        len(markers),
    )

    # ---- subtropical high ridge detection (surface MSLP) --------------
    # Same rationale as the pressure-level ridge search: the closed
    # centre is often east of 145°E, so fall back to a ridge peak.
    # Only skip ridge search if a *meaningful* closed high (≥ 1014 hPa)
    # already exists in the subtropical eastern sector.
    has_subtropical_surface_high = any(
        marker.kind == "high-pressure"
        and marker.latitude < 35.0
        and marker.longitude > 100.0
        and (marker.central_pressure_hpa or 0) >= 1014.0
        for marker in markers
    )
    if not has_subtropical_surface_high:
        ridge = _detect_mslp_ridge(
            pressure,
            subset.latitude,
            subset.longitude,
            subset.valid_at,
        )
        markers.extend(ridge)

    return markers


def _detect_mslp_ridge(
    pressure: np.ndarray,
    latitude: np.ndarray,
    longitude: np.ndarray,
    valid_at: object,
) -> list[CycloneMarker]:
    """Find the subtropical high ridge peak in the surface MSLP field."""
    lat_min, lat_max = 15.0, 35.0
    lon_min, lon_max = 105.0, 145.0
    lat_mask = (latitude >= lat_min) & (latitude <= lat_max)
    lon_mask = (longitude >= lon_min) & (longitude <= lon_max)
    if not lat_mask.any() or not lon_mask.any():
        return []

    sub_pres = pressure[lat_mask, :][:, lon_mask]
    sub_lat = latitude[lat_mask]
    sub_lon = longitude[lon_mask]
    finite = np.isfinite(sub_pres)
    if not finite.any():
        return []

    max_pres = float(np.nanmax(sub_pres))
    if max_pres < 1010.0:
        return []

    # Broad smoothing for the ridge-scale peak (~2° sigma).
    smoothed = smooth_field(sub_pres, sigma_gridpoints=8.0)
    peak_idx = np.unravel_index(np.nanargmax(smoothed), smoothed.shape)
    peak_lat = float(sub_lat[peak_idx[0]])
    peak_lon = float(sub_lon[peak_idx[1]])
    peak_pres = float(sub_pres[peak_idx[0], peak_idx[1]])

    if not np.isfinite(peak_pres) or peak_pres < 1010.0:
        return []

    return [
        CycloneMarker(
            id="objective-high-ridge-1",
            kind="high-pressure",
            valid_at=valid_at,
            latitude=peak_lat,
            longitude=peak_lon,
            central_pressure_hpa=round(peak_pres),
            source=(
                "Ridge-peak detection on smoothed ECMWF MSLP"
            ),
            confidence=(
                "high" if peak_pres >= 1016.0 else "medium"
            ),
        )
    ]


def detect_pressure_level_centres(
    grid: WeatherGrid,
    *,
    domain: WeatherMapDomain,
    pressure_hpa: int,
    maximum_centres_per_kind: int = 3,
) -> list[CycloneMarker]:
    """Locate H/L centres independently on one pressure-level height field."""
    if pressure_hpa not in {850, 500, 200}:
        raise ValueError("pressure_hpa must be one of 850, 500 or 200")
    subset = grid.subset(domain)
    field_name = f"geopotential_height_{pressure_hpa}_gpm"
    sigma = {850: 1.5, 500: 1.5, 200: 1.5}[pressure_hpa]
    # Broader subtropical highs (especially at 500 hPa) have gentler
    # curvature and need a lower prominence floor; otherwise the
    # western Pacific subtropical high ridge is invisible.
    prominence_threshold = {850: 18.0, 500: 12.0, 200: 30.0}[
        pressure_hpa
    ]
    height = smooth_field(
        subset.fields[field_name],
        sigma_gridpoints=sigma,
    )
    surface_pressure = subset.fields.get("surface_pressure_hpa")
    if surface_pressure is not None:
        height = np.where(
            surface_pressure >= pressure_hpa,
            height,
            np.nan,
        )
    grid_spacing = max(
        float(np.nanmedian(np.diff(subset.longitude))),
        float(np.nanmedian(np.diff(subset.latitude))),
    )
    neighbourhood = _odd_window(max(11, round(7.0 / grid_spacing)))
    ring_radius = max(7, round(4.0 / grid_spacing))
    centres: list[CycloneMarker] = []
    for kind, filtered, sign in (
        (
            "low-pressure",
            minimum_filter(
                np.where(np.isfinite(height), height, np.inf),
                size=neighbourhood,
                mode="nearest",
            ),
            1.0,
        ),
        (
            "high-pressure",
            maximum_filter(
                np.where(np.isfinite(height), height, -np.inf),
                size=neighbourhood,
                mode="nearest",
            ),
            -1.0,
        ),
    ):
        candidates = np.argwhere(
            np.isfinite(height)
            & np.isclose(height, filtered, atol=0.05)
        )
        ranked: list[tuple[float, float, int, int]] = []
        signed_height = height * sign
        for latitude_index, longitude_index in candidates:
            latitude = float(subset.latitude[latitude_index])
            longitude = float(subset.longitude[longitude_index])
            if (
                latitude < domain.south + 1.5
                or latitude > domain.north - 1.5
                or longitude < domain.west + 1.5
                or longitude > domain.east - 1.5
            ):
                continue
            prominence = _surrounding_depth(
                signed_height,
                int(latitude_index),
                int(longitude_index),
                ring_radius,
            )
            if (
                not np.isfinite(prominence)
                or prominence < prominence_threshold
            ):
                continue
            ranked.append(
                (
                    -prominence,
                    float(height[latitude_index, longitude_index]) * sign,
                    int(latitude_index),
                    int(longitude_index),
                )
            )

        selected: list[CycloneMarker] = []
        for (
            negative_prominence,
            _,
            latitude_index,
            longitude_index,
        ) in sorted(ranked):
            latitude = float(subset.latitude[latitude_index])
            longitude = float(subset.longitude[longitude_index])
            if any(
                _angular_distance_degrees(
                    latitude,
                    longitude,
                    marker.latitude,
                    marker.longitude,
                )
                < 7.0
                for marker in selected
            ):
                continue
            selected.append(
                CycloneMarker(
                    id=(
                        f"{pressure_hpa}-"
                        f"{'low' if kind == 'low-pressure' else 'high'}-"
                        f"{len(selected) + 1}"
                    ),
                    kind=kind,
                    valid_at=subset.valid_at,
                    latitude=latitude,
                    longitude=longitude,
                    central_height_dam=round(
                        float(height[latitude_index, longitude_index]) / 10,
                        1,
                    ),
                    source=(
                        "Objective analysis of smoothed ECMWF "
                        f"{pressure_hpa} hPa geopotential height"
                    ),
                    confidence=(
                        "high"
                        if -negative_prominence
                        >= prominence_threshold * 1.6
                        else "medium"
                    ),
                )
            )
            if len(selected) >= maximum_centres_per_kind:
                break
        centres.extend(selected)

    # ---- subtropical / South-Asian high ridge detection -----------------
    # Large-scale anticyclones (western Pacific subtropical high,
    # South Asian high) often have their closed centres outside the
    # domain.  Fall back to a ridge-peak search in the relevant band
    # when no closed high was found in the warm-sector latitudes.
    ridge_params = _RIDGE_PARAMS.get(pressure_hpa)
    if ridge_params is not None:
        # Only consider highs in the eastern part of the domain
        # (> 100°E) when deciding whether the subtropical / monsoon
        # high has already been found.  Continental / Tibetan Plateau
        # highs further west should not block the ridge search.
        has_sector_high = any(
            marker.kind == "high-pressure"
            and marker.latitude < ridge_params["lat_max"]
            and marker.longitude > 100.0
            for marker in centres
        )
        if not has_sector_high:
            ridge = _detect_high_ridge(
                height,
                subset.latitude,
                subset.longitude,
                subset.valid_at,
                maximum_centres_per_kind,
                pressure_hpa=pressure_hpa,
                **ridge_params,
            )
            centres.extend(ridge)

    return centres


# Per-level parameters for ridge-peak detection.
# lat_min / lat_max / lon_min / lon_max : search window.
# min_height_gpm : the isohypse that must exist inside the window.
# label           : human-readable system name.
_RIDGE_PARAMS: dict[int, dict[str, object]] = {
    850: {
        "lat_min": 15.0,
        "lat_max": 35.0,
        "lon_min": 105.0,
        "lon_max": 145.0,
        "min_height_gpm": 1480,
        "label": "Western Pacific subtropical high",
    },
    500: {
        "lat_min": 15.0,
        "lat_max": 35.0,
        "lon_min": 100.0,
        "lon_max": 145.0,
        "min_height_gpm": 5860,
        "label": "Western Pacific subtropical high",
    },
    200: {
        "lat_min": 20.0,
        "lat_max": 40.0,
        "lon_min": 70.0,
        "lon_max": 110.0,
        "min_height_gpm": 12300,
        "label": "South Asian high",
    },
}


def _detect_high_ridge(
    height: np.ndarray,
    latitude: np.ndarray,
    longitude: np.ndarray,
    valid_at: object,
    maximum_centres: int,
    *,
    pressure_hpa: int,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    min_height_gpm: float,
    label: str,
) -> list[CycloneMarker]:
    """Find a large-scale anticyclone ridge peak within the domain.

    Searches the specified window for the point of maximum geopotential
    height, provided *min_height_gpm* is present.  Used when the closed
    circulation centre lies outside the domain boundary.
    """
    lat_mask = (latitude >= lat_min) & (latitude <= lat_max)
    lon_mask = (longitude >= lon_min) & (longitude <= lon_max)
    if not lat_mask.any() or not lon_mask.any():
        return []

    sub_height = height[lat_mask, :][:, lon_mask]
    sub_lat = latitude[lat_mask]
    sub_lon = longitude[lon_mask]
    finite = np.isfinite(sub_height)
    if not finite.any():
        return []

    max_height = float(np.nanmax(sub_height))
    if max_height < min_height_gpm:
        return []

    # Broad smoothing to capture the ridge-scale peak (~2° sigma).
    smoothed = smooth_field(sub_height, sigma_gridpoints=8.0)
    peak_idx = np.unravel_index(np.nanargmax(smoothed), smoothed.shape)
    peak_lat = float(sub_lat[peak_idx[0]])
    peak_lon = float(sub_lon[peak_idx[1]])
    peak_height = float(sub_height[peak_idx[0], peak_idx[1]])

    if not np.isfinite(peak_height) or peak_height < min_height_gpm:
        return []

    markers: list[CycloneMarker] = []
    markers.append(
        CycloneMarker(
            id=f"{pressure_hpa}-high-ridge-1",
            kind="high-pressure",
            valid_at=valid_at,
            latitude=peak_lat,
            longitude=peak_lon,
            central_height_dam=round(peak_height / 10, 1),
            source=(
                f"Ridge-peak detection on smoothed ECMWF "
                f"{pressure_hpa} hPa geopotential height"
            ),
            confidence=(
                "high" if peak_height >= min_height_gpm * 1.005
                else "medium"
            ),
        )
    )
    return markers


def merge_cyclone_markers(
    *groups: Iterable[CycloneMarker],
) -> list[CycloneMarker]:
    """Merge overlay sources while keeping stable input order."""
    merged: list[CycloneMarker] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for marker in group:
            key = (marker.kind, marker.id)
            if key in seen:
                continue
            if (
                marker.kind == "low-pressure"
                and any(
                    existing.kind == "tropical"
                    and _angular_distance_degrees(
                        marker.latitude,
                        marker.longitude,
                        existing.latitude,
                        existing.longitude,
                    )
                    < 5.0
                    for existing in merged
                )
            ):
                continue
            seen.add(key)
            merged.append(marker)
    return merged


def _surrounding_depth(
    pressure: np.ndarray,
    latitude_index: int,
    longitude_index: int,
    radius: int,
) -> float:
    y_start = max(0, latitude_index - radius)
    y_stop = min(pressure.shape[0], latitude_index + radius + 1)
    x_start = max(0, longitude_index - radius)
    x_stop = min(pressure.shape[1], longitude_index + radius + 1)
    window = pressure[y_start:y_stop, x_start:x_stop]
    if window.size < 9:
        return float("nan")
    y_coordinates, x_coordinates = np.ogrid[
        y_start:y_stop,
        x_start:x_stop,
    ]
    distance = np.hypot(
        y_coordinates - latitude_index,
        x_coordinates - longitude_index,
    )
    ring = window[
        (distance >= radius * 0.72)
        & (distance <= radius)
    ]
    if not np.isfinite(ring).any():
        return float("nan")
    return float(
        np.nanmean(ring)
        - pressure[latitude_index, longitude_index]
    )


def _angular_distance_degrees(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    mean_latitude = np.radians((latitude_a + latitude_b) / 2)
    longitude_distance = (
        (longitude_a - longitude_b) * np.cos(mean_latitude)
    )
    return float(
        np.hypot(
            latitude_a - latitude_b,
            longitude_distance,
        )
    )


def _odd_window(value: int) -> int:
    return value if value % 2 else value + 1
