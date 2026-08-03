from __future__ import annotations

import logging
from collections.abc import Iterable

import numpy as np
from contourpy import contour_generator
from scipy.ndimage import gaussian_filter, maximum_filter, minimum_filter

from .fields import WeatherGrid
from .models import (
    CycloneMarker,
    SynopticFeature,
    WeatherMapDomain,
)

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


def detect_surface_fronts(
    grid: WeatherGrid,
    *,
    domain: WeatherMapDomain,
    maximum_features: int = 4,
) -> list[SynopticFeature]:
    """Diagnose coherent surface fronts from thermodynamic and wind fields.

    The axis starts from the zero contour of the thermal-front parameter
    (TFP). Weak or noisy pieces are removed with temperature-gradient,
    deformation/convergence, terrain, length, and continuity tests. The
    sign of low-level temperature advection separates cold and warm fronts;
    weak cross-front advection is retained as stationary.

    This is objective guidance from one model background. It is intentionally
    conservative and is not a replacement for a forecaster's hand analysis.
    """
    subset = grid.subset(domain)
    required = {
        "temperature_2m_c",
        "wind_u_10m_ms",
        "wind_v_10m_ms",
    }
    if not required.issubset(subset.fields):
        return []

    temperature = smooth_field(
        subset.fields["temperature_2m_c"],
        sigma_gridpoints=2.4,
    )
    u_wind = smooth_field(
        subset.fields["wind_u_10m_ms"],
        sigma_gridpoints=1.5,
    )
    v_wind = smooth_field(
        subset.fields["wind_v_10m_ms"],
        sigma_gridpoints=1.5,
    )
    dtdx, dtdy = _geospatial_gradient(
        temperature,
        subset.longitude,
        subset.latitude,
    )
    thermal_gradient = np.hypot(dtdx, dtdy)
    gradient_x, gradient_y = _geospatial_gradient(
        thermal_gradient,
        subset.longitude,
        subset.latitude,
    )
    tfp = smooth_field(
        -np.divide(
            gradient_x * dtdx + gradient_y * dtdy,
            thermal_gradient,
            out=np.zeros_like(thermal_gradient),
            where=thermal_gradient > 1e-12,
        ),
        sigma_gridpoints=1.25,
    )

    dudx, dudy = _geospatial_gradient(
        u_wind,
        subset.longitude,
        subset.latitude,
    )
    dvdx, dvdy = _geospatial_gradient(
        v_wind,
        subset.longitude,
        subset.latitude,
    )
    divergence = dudx + dvdy
    stretching = dudx - dvdy
    shearing = dvdx + dudy
    deformation = np.hypot(stretching, shearing)
    deformation_axis = 0.5 * np.arctan2(shearing, stretching)
    sin_beta = np.divide(
        dtdx * np.cos(deformation_axis)
        + dtdy * np.sin(deformation_axis),
        thermal_gradient,
        out=np.zeros_like(thermal_gradient),
        where=thermal_gradient > 1e-12,
    )
    # Petterssen frontogenesis, expressed as K / (100 km) / 3 h.
    frontogenesis = (
        0.5
        * thermal_gradient
        * (deformation * (1 - 2 * sin_beta**2) - divergence)
        * 1.08e9
    )
    thermal_gradient_scaled = thermal_gradient * 100_000.0
    deformation_scaled = deformation * 100_000.0
    temperature_advection = (
        u_wind * dtdx + v_wind * dtdy
    ) * 10_800.0

    finite = (
        np.isfinite(tfp)
        & np.isfinite(thermal_gradient_scaled)
        & np.isfinite(frontogenesis)
        & np.isfinite(deformation_scaled)
    )
    latitude_grid = np.broadcast_to(
        subset.latitude[:, None],
        temperature.shape,
    )
    finite &= latitude_grid >= max(18.0, domain.south + 1.0)
    surface_pressure = subset.fields.get("surface_pressure_hpa")
    if surface_pressure is not None:
        finite &= surface_pressure >= 850.0
    if finite.sum() < 16:
        return []

    gradient_threshold = max(
        0.85,
        min(
            2.2,
            float(np.nanpercentile(thermal_gradient_scaled[finite], 84)),
        ),
    )
    deformation_threshold = max(
        0.55,
        float(np.nanpercentile(deformation_scaled[finite], 65)),
    )
    convergence_scaled = -divergence * 100_000.0
    candidate = (
        finite
        & (thermal_gradient_scaled >= gradient_threshold)
        & (deformation_scaled >= deformation_threshold)
        & (frontogenesis >= 0.02)
        & (
            (convergence_scaled >= 0.05)
            | (deformation_scaled >= deformation_threshold * 1.2)
        )
    )
    # TFP zero lines sit on the warm edge of the baroclinic zone. A small
    # dilation keeps the screening mask collocated after finite differencing.
    candidate = maximum_filter(
        candidate.astype(np.uint8),
        size=3,
        mode="nearest",
    ).astype(bool)

    features: list[SynopticFeature] = []
    contour_tfp = np.where(
        finite & (thermal_gradient_scaled >= gradient_threshold * 0.35),
        tfp,
        np.nan,
    )
    for line in _zero_contours(
        subset.longitude,
        subset.latitude,
        contour_tfp,
    ):
        indices = _line_grid_indices(
            line,
            subset.longitude,
            subset.latitude,
        )
        qualifying = candidate[indices]
        for segment in _split_masked_polyline(line, qualifying):
            if _polyline_length_km(segment) < 550.0:
                continue
            segment_indices = _line_grid_indices(
                segment,
                subset.longitude,
                subset.latitude,
            )
            gradient_value = float(
                np.nanmedian(thermal_gradient_scaled[segment_indices])
            )
            if gradient_value < gradient_threshold:
                continue
            advection_value = float(
                np.nanmedian(temperature_advection[segment_indices])
            )
            frontogenesis_value = float(
                np.nanmedian(frontogenesis[segment_indices])
            )
            deformation_value = float(
                np.nanmedian(deformation_scaled[segment_indices])
            )
            if (
                frontogenesis_value < 0.02
                or deformation_value < deformation_threshold
            ):
                continue
            if advection_value >= 0.45:
                kind = "cold-front"
            elif advection_value <= -0.45:
                kind = "warm-front"
            else:
                kind = "stationary-front"
            length_km = _polyline_length_km(segment)
            score = (
                gradient_value / gradient_threshold
                + max(0.0, frontogenesis_value) / 0.8
                + min(1.5, length_km / 1_000.0)
            )
            coordinates = _prepare_feature_coordinates(segment)
            if len(coordinates) < 2:
                continue
            features.append(
                SynopticFeature(
                    id=f"surface-front-{len(features) + 1}",
                    kind=kind,
                    valid_at=subset.valid_at,
                    coordinates=coordinates,
                    confidence=(
                        "high"
                        if gradient_value >= gradient_threshold * 1.2
                        and length_km >= 700.0
                        and frontogenesis_value >= 0.05
                        else "medium"
                    ),
                    score=round(max(0.0, score), 3),
                    source=(
                        "ECMWF objective TFP, Petterssen frontogenesis, "
                        "low-level deformation and thermal-advection analysis"
                    ),
                )
            )

    return _rank_and_deduplicate_features(
        features,
        maximum_features=maximum_features,
    )


def detect_height_axes(
    grid: WeatherGrid,
    *,
    domain: WeatherMapDomain,
    pressure_hpa: int = 500,
    maximum_features_per_kind: int = 4,
) -> list[SynopticFeature]:
    """Detect coherent trough and ridge axes on an isobaric height field.

    Axes begin at zero meridional geostrophic wind (the zero contour of the
    zonal height gradient). The sign and persistence of geopotential-contour
    curvature distinguish troughs from ridges, while minimum length and
    curvature thresholds suppress grid-scale and nearly zonal artefacts.
    """
    subset = grid.subset(domain)
    field_name = f"geopotential_height_{pressure_hpa}_gpm"
    if field_name not in subset.fields:
        return []
    height = smooth_field(
        subset.fields[field_name],
        sigma_gridpoints=3.0,
    )
    dzdx, dzdy = _geospatial_gradient(
        height,
        subset.longitude,
        subset.latitude,
    )
    dzdxx, dzdxy = _geospatial_gradient(
        dzdx,
        subset.longitude,
        subset.latitude,
    )
    _, dzdyy = _geospatial_gradient(
        dzdy,
        subset.longitude,
        subset.latitude,
    )
    gradient_squared = dzdx**2 + dzdy**2
    curvature = np.divide(
        (
            dzdxx * dzdy**2
            - 2 * dzdxy * dzdx * dzdy
            + dzdyy * dzdx**2
        ),
        np.power(gradient_squared, 1.5),
        out=np.zeros_like(height),
        where=gradient_squared > 1e-16,
    ) * 100_000.0
    curvature = smooth_field(curvature, sigma_gridpoints=1.0)
    gradient_scaled = np.sqrt(gradient_squared) * 100_000.0

    latitude_grid = np.broadcast_to(subset.latitude[:, None], height.shape)
    finite = (
        np.isfinite(curvature)
        & np.isfinite(dzdx)
        & (gradient_scaled >= 4.0)
        & (latitude_grid >= max(20.0, domain.south + 1.5))
        & (latitude_grid <= domain.north - 1.0)
    )
    surface_pressure = subset.fields.get("surface_pressure_hpa")
    if surface_pressure is not None:
        finite &= surface_pressure >= pressure_hpa
    if finite.sum() < 16:
        return []
    curvature_threshold = max(
        0.025,
        min(
            0.16,
            float(np.nanpercentile(np.abs(curvature[finite]), 64)),
        ),
    )
    masks = {
        "trough-axis": finite & (curvature >= curvature_threshold),
        "ridge-axis": finite & (curvature <= -curvature_threshold),
    }
    masks = {
        kind: maximum_filter(
            mask.astype(np.uint8),
            size=7,
            mode="nearest",
        ).astype(bool)
        for kind, mask in masks.items()
    }

    features: list[SynopticFeature] = []
    axis_field = smooth_field(dzdx * 100_000.0, sigma_gridpoints=1.0)
    for line in _zero_contours(
        subset.longitude,
        subset.latitude,
        axis_field,
    ):
        indices = _line_grid_indices(
            line,
            subset.longitude,
            subset.latitude,
        )
        for kind, mask in masks.items():
            for segment in _split_masked_polyline(line, mask[indices]):
                length_km = _polyline_length_km(segment)
                if length_km < 650.0:
                    continue
                segment_indices = _line_grid_indices(
                    segment,
                    subset.longitude,
                    subset.latitude,
                )
                signed_curvature = curvature[segment_indices]
                expected_sign = 1.0 if kind == "trough-axis" else -1.0
                sign_fraction = float(
                    np.mean(signed_curvature * expected_sign > 0)
                )
                strength = float(np.nanmedian(np.abs(signed_curvature)))
                if sign_fraction < 0.72 or strength < curvature_threshold:
                    continue
                coordinates = _prepare_feature_coordinates(segment)
                if len(coordinates) < 2:
                    continue
                score = (
                    strength / curvature_threshold
                    + min(1.75, length_km / 1_200.0)
                    + sign_fraction
                )
                features.append(
                    SynopticFeature(
                        id=(
                            f"{pressure_hpa}-"
                            f"{'trough' if kind == 'trough-axis' else 'ridge'}-"
                            f"{len(features) + 1}"
                        ),
                        kind=kind,
                        valid_at=subset.valid_at,
                        coordinates=coordinates,
                        pressure_hpa=pressure_hpa,
                        confidence=(
                            "high"
                            if strength >= curvature_threshold * 1.4
                            and length_km >= 900.0
                            and sign_fraction >= 0.82
                            else "medium"
                        ),
                        score=round(max(0.0, score), 3),
                        source=(
                            f"Objective {pressure_hpa} hPa geopotential-height "
                            "curvature and zero-meridional-geostrophic-wind analysis"
                        ),
                    )
                )

    selected: list[SynopticFeature] = []
    for kind in ("trough-axis", "ridge-axis"):
        selected.extend(
            _rank_and_deduplicate_features(
                [feature for feature in features if feature.kind == kind],
                maximum_features=maximum_features_per_kind,
            )
        )
    return selected


def _geospatial_gradient(
    values: np.ndarray,
    longitude: np.ndarray,
    latitude: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return x/y derivatives on a regular lat/lon grid in SI metres."""
    earth_radius_m = 6_371_008.8
    longitude_radians = np.radians(np.asarray(longitude, dtype=float))
    latitude_radians = np.radians(np.asarray(latitude, dtype=float))
    derivative_lon = np.gradient(
        np.asarray(values, dtype=float),
        longitude_radians,
        axis=1,
        edge_order=2,
    )
    cosine_latitude = np.cos(latitude_radians)[:, None]
    derivative_x = np.divide(
        derivative_lon,
        earth_radius_m * cosine_latitude,
        out=np.full_like(derivative_lon, np.nan),
        where=np.abs(cosine_latitude) > 1e-6,
    )
    derivative_y = np.gradient(
        np.asarray(values, dtype=float),
        latitude_radians * earth_radius_m,
        axis=0,
        edge_order=2,
    )
    return derivative_x, derivative_y


def _zero_contours(
    longitude: np.ndarray,
    latitude: np.ndarray,
    values: np.ndarray,
) -> list[np.ndarray]:
    finite_values = np.ma.masked_invalid(np.asarray(values, dtype=float))
    if finite_values.count() < 4:
        return []
    minimum = float(finite_values.min())
    maximum = float(finite_values.max())
    if minimum > 0 or maximum < 0 or minimum == maximum:
        return []
    generator = contour_generator(
        x=np.asarray(longitude, dtype=float),
        y=np.asarray(latitude, dtype=float),
        z=finite_values,
        corner_mask=True,
    )
    return [
        np.asarray(line, dtype=float)
        for line in generator.lines(0.0)
        if len(line) >= 2
    ]


def _line_grid_indices(
    line: np.ndarray,
    longitude: np.ndarray,
    latitude: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    lon_indices = _nearest_coordinate_indices(line[:, 0], longitude)
    lat_indices = _nearest_coordinate_indices(line[:, 1], latitude)
    return lat_indices, lon_indices


def _nearest_coordinate_indices(
    values: np.ndarray,
    coordinates: np.ndarray,
) -> np.ndarray:
    indices = np.searchsorted(coordinates, values)
    indices = np.clip(indices, 1, len(coordinates) - 1)
    left = coordinates[indices - 1]
    right = coordinates[indices]
    use_left = np.abs(values - left) <= np.abs(values - right)
    return np.where(use_left, indices - 1, indices).astype(int)


def _split_masked_polyline(
    line: np.ndarray,
    qualifying: np.ndarray,
    *,
    maximum_gap_points: int = 2,
) -> list[np.ndarray]:
    segments: list[np.ndarray] = []
    start: int | None = None
    gap = 0
    for index, is_valid in enumerate(qualifying):
        if is_valid:
            if start is None:
                start = index
            gap = 0
            continue
        if start is None:
            continue
        gap += 1
        if gap > maximum_gap_points:
            stop = index - gap + 1
            if stop - start >= 2:
                segments.append(line[start:stop])
            start = None
            gap = 0
    if start is not None:
        stop = len(line) - gap
        if stop - start >= 2:
            segments.append(line[start:stop])
    return segments


def _prepare_feature_coordinates(
    line: np.ndarray,
) -> list[tuple[float, float]]:
    if len(line) < 2:
        return []
    window = min(7, len(line) if len(line) % 2 else len(line) - 1)
    if window >= 3:
        kernel = np.ones(window, dtype=float) / window
        padding = window // 2
        longitude = np.convolve(
            np.pad(line[:, 0], padding, mode="edge"),
            kernel,
            mode="valid",
        )
        latitude = np.convolve(
            np.pad(line[:, 1], padding, mode="edge"),
            kernel,
            mode="valid",
        )
        smoothed = np.column_stack((longitude, latitude))
    else:
        smoothed = line
    stride = max(1, len(smoothed) // 36)
    sampled = smoothed[::stride]
    if not np.allclose(sampled[-1], smoothed[-1]):
        sampled = np.vstack((sampled, smoothed[-1]))
    return [
        (round(float(point[0]), 3), round(float(point[1]), 3))
        for point in sampled
    ]


def _polyline_length_km(line: np.ndarray) -> float:
    if len(line) < 2:
        return 0.0
    latitude_1 = np.radians(line[:-1, 1])
    latitude_2 = np.radians(line[1:, 1])
    latitude_delta = latitude_2 - latitude_1
    longitude_delta = np.radians(line[1:, 0] - line[:-1, 0])
    haversine = (
        np.sin(latitude_delta / 2) ** 2
        + np.cos(latitude_1)
        * np.cos(latitude_2)
        * np.sin(longitude_delta / 2) ** 2
    )
    distance = 2 * 6_371.0088 * np.arcsin(
        np.sqrt(np.clip(haversine, 0, 1))
    )
    return float(np.nansum(distance))


def _rank_and_deduplicate_features(
    features: list[SynopticFeature],
    *,
    maximum_features: int,
) -> list[SynopticFeature]:
    selected: list[SynopticFeature] = []
    for feature in sorted(features, key=lambda item: item.score, reverse=True):
        midpoint = feature.coordinates[len(feature.coordinates) // 2]
        duplicate = False
        for existing in selected:
            if existing.kind != feature.kind:
                continue
            existing_midpoint = existing.coordinates[
                len(existing.coordinates) // 2
            ]
            if _angular_distance_degrees(
                midpoint[1],
                midpoint[0],
                existing_midpoint[1],
                existing_midpoint[0],
            ) < 4.0:
                duplicate = True
                break
        if duplicate:
            continue
        selected.append(feature)
        if len(selected) >= maximum_features:
            break
    return selected


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
