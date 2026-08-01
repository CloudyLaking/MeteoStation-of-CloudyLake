from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.font_manager import FontProperties
from matplotlib.collections import LineCollection
from scipy.ndimage import maximum_filter, minimum_filter

from .analysis import smooth_field
from .basemap import LocalBoundaryLayer, TiandituBasemap
from .fields import WeatherGrid
from .models import CycloneMarker, WeatherMapDomain, WeatherMapPreview


WIND_COLORS = LinearSegmentedColormap.from_list(
    "cloudylake-wind",
    ["#ffffff", "#f3eadf", "#ead8bd", "#dcb49a", "#a68b99"],
)
HUMIDITY_COLORS = LinearSegmentedColormap.from_list(
    "cloudylake-humidity",
    ["#b9957d", "#eee1cf", "#ffffff", "#b8d6ce", "#5f928c"],
)
HEIGHT_ANOMALY_COLORS = LinearSegmentedColormap.from_list(
    "cloudylake-height-anomaly",
    [
        "#557f98",
        "#9dbfcb",
        "#dce9e7",
        "#ffffff",
        "#f5e8bc",
        "#dda96c",
        "#b86450",
    ],
)
FIGURE_SIZE_INCHES = (11.5, 8.7)
MAP_FIGURE_BOUNDS = {
    "left": 0.075,
    "right": 0.860,
    "bottom": 0.100,
    "top": 0.860,
}
COLORBAR_FIGURE_BOUNDS = [0.885, 0.100, 0.025, 0.760]
SMOOTHING_SIGMA_GRIDPOINTS = {
    "surface_mslp": 2.25,
    "surface_wind_speed": 1.25,
    "850_humidity": 1.50,
    "850_height": 1.50,
    "500_height_anomaly": 2.00,
    "500_height": 1.50,
    "200_wind_speed": 1.50,
    "200_height": 1.50,
}


def render_weather_map_preview(
    grid: WeatherGrid,
    *,
    layer_id: str,
    domain: WeatherMapDomain,
    preview_root: Path,
    font_path: Path | None = None,
    cyclone_markers: list[CycloneMarker] | None = None,
    base_map: TiandituBasemap | None = None,
    boundary_layer: LocalBoundaryLayer | None = None,
) -> WeatherMapPreview:
    """Render one China weather-analysis preview."""
    subset = grid.subset(domain)
    figure, axis = plt.subplots(
        figsize=FIGURE_SIZE_INCHES,
        facecolor="white",
    )
    figure.subplots_adjust(
        left=MAP_FIGURE_BOUNDS["left"],
        right=MAP_FIGURE_BOUNDS["right"],
        top=MAP_FIGURE_BOUNDS["top"],
        bottom=MAP_FIGURE_BOUNDS["bottom"],
    )
    font = (
        FontProperties(fname=str(font_path))
        if font_path and Path(font_path).exists()
        else None
    )
    longitude_grid, latitude_grid = np.meshgrid(
        subset.longitude,
        subset.latitude,
    )
    if base_map is not None:
        axis.imshow(
            base_map.vector,
            extent=base_map.extent,
            origin="upper",
            zorder=-20,
            interpolation="bilinear",
        )
    if layer_id in {"surface", "composite"}:
        draw_surface(axis, figure, longitude_grid, latitude_grid, subset)
        title = "Surface Analysis Background"
    elif layer_id == "850":
        draw_pressure_level(
            axis,
            figure,
            longitude_grid,
            latitude_grid,
            subset,
            pressure_hpa=850,
            shade="humidity",
        )
        title = "850 hPa Analysis Background"
    elif layer_id == "500":
        draw_pressure_level(
            axis,
            figure,
            longitude_grid,
            latitude_grid,
            subset,
            pressure_hpa=500,
            shade="height_anomaly",
        )
        title = "500 hPa Height Anomaly / Height / Wind"
    elif layer_id == "200":
        draw_pressure_level(
            axis,
            figure,
            longitude_grid,
            latitude_grid,
            subset,
            pressure_hpa=200,
            shade="wind",
        )
        title = "200 hPa Analysis Background"
    else:
        plt.close(figure)
        raise ValueError(f"Unsupported weather-map preview layer: {layer_id}")

    if base_map is not None:
        axis.imshow(
            base_map.boundaries,
            extent=base_map.extent,
            origin="upper",
            zorder=6,
            interpolation="bilinear",
        )
        axis.imshow(
            base_map.labels,
            extent=base_map.extent,
            origin="upper",
            zorder=6.2,
            interpolation="bilinear",
        )
    if boundary_layer is not None:
        draw_local_boundaries(axis, boundary_layer)
        draw_south_china_sea_inset(
            figure,
            boundary_layer,
            font=font,
        )
    draw_cyclone_markers(
        axis,
        cyclone_markers or [],
        font=font,
    )
    axis.set_xlim(domain.west, domain.east)
    axis.set_ylim(domain.south, domain.north)
    # At the domain midpoint, one degree of longitude is about cos(latitude)
    # times one degree of latitude. This keeps China from looking either
    # vertically squeezed or unnaturally narrow.
    central_latitude = (domain.south + domain.north) / 2
    axis.set_aspect(
        1 / np.cos(np.radians(central_latitude)),
        adjustable="box",
    )
    axis.set_facecolor("#ffffff")
    axis.set_xlabel("Longitude", fontproperties=font, fontsize=8)
    axis.set_ylabel("Latitude", fontproperties=font, fontsize=8)
    axis.tick_params(labelsize=7.5)
    axis.grid(
        color="#958a80",
        linestyle="--",
        linewidth=0.5,
        alpha=0.28,
    )
    axis.set_title(
        f"{title}\n{subset.valid_at:%Y-%m-%d %H:00 UTC}",
        loc="left",
        fontsize=14,
        fontweight="bold",
        fontproperties=font,
        color="#263943",
        pad=16,
    )
    axis.set_title(
        (
            "TIANDITU STANDARD MAP SERVICE\n"
            f"Service review No. {base_map.source_review_number}"
            if base_map is not None
            else (
                "TIANDITU BOUNDARY DATA\n"
                "National and provincial boundaries"
                if boundary_layer is not None
                else "ECMWF FIELD\nNo administrative boundaries"
            )
        ),
        loc="right",
        fontsize=8.5,
        fontproperties=font,
        color="#a45247",
        pad=18,
    )
    source_note = subset.source
    if layer_id == "500":
        normal_metadata = subset.metadata.get(
            "height_climatology_500",
            {},
        )
        if isinstance(normal_metadata, dict):
            normal_period = normal_metadata.get(
                "normal_period",
                "1991-2020",
            )
            source_note += f" · ERA5 {normal_period} monthly height normal"
    figure.text(
        MAP_FIGURE_BOUNDS["left"],
        0.035,
        f"Source: {source_note} · CloudyLake's Observatory · meteostation.top",
        fontsize=7.5,
        color="#687579",
        fontproperties=font,
    )
    figure.text(
        MAP_FIGURE_BOUNDS["right"],
        0.955,
        "@CloudyLake",
        ha="right",
        va="top",
        fontsize=9,
        fontweight="bold",
        color="#126e68",
        fontproperties=font,
    )

    directory = (
        Path(preview_root)
        / "weather_maps"
        / f"{subset.valid_at:%Y}"
        / f"{subset.valid_at:%m}"
        / f"{subset.valid_at:%d}"
    )
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{subset.valid_at:%H}_{layer_id}"
    image_path = directory / f"{stem}.png"
    metadata_path = directory / f"{stem}.json"
    temporary_image = image_path.with_suffix(".png.tmp")
    figure.savefig(
        temporary_image,
        format="png",
        dpi=180,
        facecolor="white",
    )
    plt.close(figure)
    os.replace(temporary_image, image_path)
    metadata = {
        "layer_id": layer_id,
        "valid_at": subset.valid_at.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": subset.source,
        "publication_status": "development-preview",
        "base_map_status": (
            "official-service-preview"
            if base_map is not None
            else (
                "official-boundary-preview"
                if boundary_layer is not None
                else "not-included"
            )
        ),
        "base_map": (
            {
                "source": "国家地理信息公共服务平台（天地图）",
                "layers": ["vec_w", "cva_w", "ibo_w"],
                "zoom": base_map.zoom,
                "service_review_number": base_map.source_review_number,
                "thematic_map_review_status": "pending",
            }
            if base_map is not None
            else None
        ),
        "boundary_layer": (
            {
                "source": boundary_layer.source,
                "source_path": boundary_layer.source_path,
                "crs": boundary_layer.crs,
                "feature_count": boundary_layer.feature_count,
                "sha256": boundary_layer.sha256,
            }
            if boundary_layer is not None
            else None
        ),
        "domain": domain.model_dump(),
        "fields": sorted(subset.fields),
        "source_metadata": subset.metadata,
        "rendering": {
            "smoothing_sigma_gridpoints": (
                SMOOTHING_SIGMA_GRIDPOINTS
            ),
            "cyclone_markers": [
                marker.model_dump(mode="json")
                for marker in (cyclone_markers or [])
            ],
        },
    }
    temporary_metadata = metadata_path.with_suffix(".json.tmp")
    temporary_metadata.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_metadata, metadata_path)
    relative_image = image_path.relative_to(preview_root).as_posix()
    relative_metadata = metadata_path.relative_to(preview_root).as_posix()
    return WeatherMapPreview(
        layer_id=layer_id,
        valid_at=subset.valid_at,
        generated_at=datetime.fromisoformat(metadata["generated_at"]),
        source=subset.source,
        image_url=f"/previews/{relative_image}",
        metadata_url=f"/previews/{relative_metadata}",
        base_map_status=metadata["base_map_status"],
    )


def draw_local_boundaries(
    axis: object,
    boundary_layer: LocalBoundaryLayer,
) -> None:
    province_collection = LineCollection(
        boundary_layer.province_lines,
        colors="#41645f",
        linewidths=0.58,
        alpha=0.9,
        zorder=6.5,
    )
    province_collection.set_clip_on(True)
    axis.add_collection(province_collection)
    boundary_collection = LineCollection(
        boundary_layer.boundary_lines,
        colors="#163f3c",
        linewidths=1.35,
        alpha=1.0,
        zorder=6.8,
    )
    boundary_collection.set_clip_on(True)
    axis.add_collection(boundary_collection)


def draw_south_china_sea_inset(
    figure: object,
    boundary_layer: LocalBoundaryLayer,
    *,
    font: FontProperties | None,
) -> None:
    """Draw the standard South China Sea islands inset from the same source."""
    inset = figure.add_axes([0.705, 0.125, 0.125, 0.235])
    inset.set_facecolor("#ffffff")
    province_collection = LineCollection(
        boundary_layer.province_lines,
        colors="#41645f",
        linewidths=0.48,
        alpha=0.9,
        zorder=2,
    )
    boundary_collection = LineCollection(
        boundary_layer.boundary_lines,
        colors="#163f3c",
        linewidths=0.9,
        alpha=1.0,
        zorder=3,
    )
    inset.add_collection(province_collection)
    inset.add_collection(boundary_collection)
    inset.set_xlim(105, 125)
    inset.set_ylim(3, 25)
    inset.set_aspect(
        1 / np.cos(np.radians(14)),
        adjustable="box",
    )
    inset.set_xticks([])
    inset.set_yticks([])
    inset.tick_params(length=0)
    for spine in inset.spines.values():
        spine.set_color("#41645f")
        spine.set_linewidth(0.65)
    inset.set_title(
        "South China Sea Islands",
        fontsize=5.5,
        fontproperties=font,
        color="#41645f",
        pad=2,
    )


def draw_surface(
    axis: object,
    figure: object,
    longitude: np.ndarray,
    latitude: np.ndarray,
    grid: WeatherGrid,
) -> None:
    mslp = smooth_field(
        require_field(grid, "mslp_hpa"),
        sigma_gridpoints=SMOOTHING_SIGMA_GRIDPOINTS[
            "surface_mslp"
        ],
    )
    u_wind = require_field(grid, "wind_u_10m_ms")
    v_wind = require_field(grid, "wind_v_10m_ms")
    speed = smooth_field(
        np.hypot(u_wind, v_wind),
        sigma_gridpoints=SMOOTHING_SIGMA_GRIDPOINTS[
            "surface_wind_speed"
        ],
    )
    maximum = max(
        20,
        round_up(float(np.nanpercentile(speed, 99)), 5),
    )
    shaded = axis.contourf(
        longitude,
        latitude,
        speed,
        levels=np.linspace(0, maximum, 17),
        cmap=WIND_COLORS,
        extend="max",
        alpha=0.76,
    )
    contour_levels = np.arange(
        np.floor(np.nanmin(mslp) / 4) * 4,
        np.ceil(np.nanmax(mslp) / 4) * 4 + 0.1,
        4,
    )
    contours = axis.contour(
        longitude,
        latitude,
        mslp,
        levels=contour_levels,
        colors="#263238",
        linewidths=0.62,
    )
    axis.clabel(contours, inline=True, fontsize=7, fmt="%.0f")
    draw_wind_barbs(axis, longitude, latitude, u_wind, v_wind)
    draw_surface_objective_features(
        axis,
        longitude,
        latitude,
        grid,
        u_wind=u_wind,
        v_wind=v_wind,
    )
    add_weather_colorbar(
        figure,
        shaded,
        "10 m wind speed (m/s)",
    )


def draw_surface_objective_features(
    axis: object,
    longitude: np.ndarray,
    latitude: np.ndarray,
    grid: WeatherGrid,
    *,
    u_wind: np.ndarray,
    v_wind: np.ndarray,
) -> None:
    """Overlay conservative temperature, moist-zone and frontal guidance.

    The marks are deliberately labelled as objective candidates. They are
    guidance derived from the same ECMWF background, not manually analysed
    fronts or official warnings.
    """
    temperature = smooth_field(
        require_field(grid, "temperature_2m_c"),
        sigma_gridpoints=2.0,
    )
    water_vapour = smooth_field(
        require_field(grid, "total_column_water_vapour_kg_m2"),
        sigma_gridpoints=2.0,
    )
    if not np.isfinite(temperature).any() or not np.isfinite(water_vapour).any():
        return

    wet_threshold = max(30.0, float(np.nanpercentile(water_vapour, 68)))
    wet_maximum = float(np.nanmax(water_vapour))
    if wet_maximum > wet_threshold:
        wet_zone = axis.contourf(
            longitude,
            latitude,
            water_vapour,
            levels=[wet_threshold, wet_maximum + 0.01],
            colors=["#168a7c"],
            alpha=0.11,
            zorder=2.6,
        )
        wet_outline = axis.contour(
            longitude,
            latitude,
            water_vapour,
            levels=[wet_threshold],
            colors="#168a7c",
            linewidths=0.72,
            linestyles="--",
            alpha=0.74,
            zorder=4.8,
        )
        axis.clabel(wet_outline, fmt={wet_threshold: "MOIST"}, fontsize=6.5)

    latitude_spacing = max(0.1, float(np.nanmedian(np.abs(np.diff(grid.latitude)))))
    longitude_spacing = max(0.1, float(np.nanmedian(np.abs(np.diff(grid.longitude)))))
    gradient_y, gradient_x = np.gradient(
        temperature,
        latitude_spacing,
        longitude_spacing,
    )
    gradient = np.hypot(gradient_x, gradient_y)
    moisture_mask = water_vapour >= float(np.nanpercentile(water_vapour, 55))
    frontal_threshold = max(1.2, float(np.nanpercentile(gradient[moisture_mask], 90)))
    frontal_signal = np.where(moisture_mask, gradient, np.nan)
    if np.nanmax(frontal_signal) > frontal_threshold:
        front = axis.contour(
            longitude,
            latitude,
            frontal_signal,
            levels=[frontal_threshold],
            colors="#2563a9",
            linewidths=1.15,
            alpha=0.82,
            zorder=5.0,
        )
        axis.clabel(
            front,
            fmt={frontal_threshold: "FRONT CAND."},
            fontsize=6.3,
            inline=True,
        )

    _draw_temperature_extrema(axis, longitude, latitude, temperature)


def _draw_temperature_extrema(
    axis: object,
    longitude: np.ndarray,
    latitude: np.ndarray,
    temperature: np.ndarray,
) -> None:
    neighbourhood = max(9, int(round(min(temperature.shape) / 9)))
    if neighbourhood % 2 == 0:
        neighbourhood += 1
    high_candidates = np.argwhere(
        np.isclose(
            temperature,
            maximum_filter(temperature, size=neighbourhood, mode="nearest"),
            atol=0.03,
        )
        & (temperature >= np.nanpercentile(temperature, 94))
    )
    low_candidates = np.argwhere(
        np.isclose(
            temperature,
            minimum_filter(temperature, size=neighbourhood, mode="nearest"),
            atol=0.03,
        )
        & (temperature <= np.nanpercentile(temperature, 6))
    )
    selected: list[tuple[float, float]] = []
    for candidates, label, color, reverse in (
        (high_candidates, "HOT", "#d97521", True),
        (low_candidates, "COLD", "#2563a9", False),
    ):
        ranked = sorted(
            candidates,
            key=lambda item: float(temperature[item[0], item[1]]),
            reverse=reverse,
        )
        count = 0
        for lat_index, lon_index in ranked:
            marker_latitude = float(latitude[lat_index, lon_index])
            marker_longitude = float(longitude[lat_index, lon_index])
            if any(
                np.hypot(marker_latitude - previous_lat, marker_longitude - previous_lon) < 7
                for previous_lat, previous_lon in selected
            ):
                continue
            value = float(temperature[lat_index, lon_index])
            axis.text(
                marker_longitude,
                marker_latitude,
                f"{label}\n{value:.0f}°C",
                ha="center",
                va="center",
                fontsize=7,
                fontweight="bold",
                color=color,
                path_effects=[
                    path_effects.Stroke(linewidth=2.4, foreground="white"),
                    path_effects.Normal(),
                ],
                zorder=7.2,
            )
            selected.append((marker_latitude, marker_longitude))
            count += 1
            if count >= 2:
                break


def draw_pressure_level(
    axis: object,
    figure: object,
    longitude: np.ndarray,
    latitude: np.ndarray,
    grid: WeatherGrid,
    *,
    pressure_hpa: int,
    shade: str,
) -> None:
    suffix = str(pressure_hpa)
    height = require_field(
        grid,
        f"geopotential_height_{suffix}_gpm",
    )
    u_wind = require_field(grid, f"wind_u_{suffix}_ms")
    v_wind = require_field(grid, f"wind_v_{suffix}_ms")
    if shade == "humidity":
        shaded_values = smooth_field(
            require_field(
                grid,
                f"relative_humidity_{suffix}_pct",
            ),
            sigma_gridpoints=SMOOTHING_SIGMA_GRIDPOINTS[
                "850_humidity"
            ],
        )
        shaded = axis.contourf(
            longitude,
            latitude,
            shaded_values,
            levels=np.arange(10, 101, 10),
            cmap=HUMIDITY_COLORS,
            extend="both",
            alpha=0.76,
        )
        colorbar_label = "Relative humidity (%)"
    elif shade == "height_anomaly":
        climatology_height = require_field(
            grid,
            "geopotential_height_500_climatology_gpm",
        )
        shaded_values = smooth_field(
            height - climatology_height,
            sigma_gridpoints=SMOOTHING_SIGMA_GRIDPOINTS[
                "500_height_anomaly"
            ],
        )
        maximum = max(
            40,
            round_up(
                float(
                    np.nanpercentile(
                        np.abs(shaded_values),
                        98,
                    )
                ),
                20,
            ),
        )
        shaded = axis.contourf(
            longitude,
            latitude,
            shaded_values,
            levels=np.linspace(-maximum, maximum, 17),
            cmap=HEIGHT_ANOMALY_COLORS,
            extend="both",
            alpha=0.76,
        )
        colorbar_label = "500 hPa height anomaly (gpm)"
    else:
        shaded_values = smooth_field(
            np.hypot(u_wind, v_wind),
            sigma_gridpoints=SMOOTHING_SIGMA_GRIDPOINTS[
                "200_wind_speed"
            ],
        )
        maximum = max(
            30,
            round_up(
                float(np.nanpercentile(shaded_values, 99)),
                5,
            ),
        )
        shaded = axis.contourf(
            longitude,
            latitude,
            shaded_values,
            levels=np.linspace(0, maximum, 17),
            cmap=WIND_COLORS,
            extend="max",
            alpha=0.76,
        )
        colorbar_label = f"{pressure_hpa} hPa wind speed (m/s)"
    height = smooth_field(
        height,
        sigma_gridpoints=SMOOTHING_SIGMA_GRIDPOINTS[
            f"{pressure_hpa}_height"
        ],
    )
    # Use 4-dagpm spacing for 500 hPa (standard subtropical-high analysis).
    if pressure_hpa == 500:
        height_interval = 40
        # Align to the classic 580 / 584 / 588 / 592 dagpm sequence.
        anchor = 5800
        height_levels = np.arange(
            anchor,
            np.ceil(np.nanmax(height) / height_interval) * height_interval + 0.1,
            height_interval,
        )
        # Also include levels below 580 if needed.
        low = np.arange(
            np.floor(np.nanmin(height) / height_interval) * height_interval,
            anchor,
            height_interval,
        )
        height_levels = np.concatenate([low, height_levels])
    else:
        height_interval = {850: 30, 500: 60, 200: 120}[pressure_hpa]
        height_levels = np.arange(
            np.floor(np.nanmin(height) / height_interval) * height_interval,
            np.ceil(np.nanmax(height) / height_interval) * height_interval + 0.1,
            height_interval,
        )
    contours = axis.contour(
        longitude,
        latitude,
        height,
        levels=height_levels,
        colors="#263238",
        linewidths=0.62,
    )
    axis.clabel(contours, inline=True, fontsize=7, fmt="%.0f")
    draw_wind_barbs(axis, longitude, latitude, u_wind, v_wind)
    add_weather_colorbar(figure, shaded, colorbar_label)


def draw_cyclone_markers(
    axis: object,
    markers: list[CycloneMarker],
    *,
    font: FontProperties | None,
) -> None:
    for marker in markers:
        if marker.kind == "tropical":
            axis.scatter(
                [marker.longitude],
                [marker.latitude],
                marker="x",
                s=74,
                linewidths=1.8,
                color="#b83b32",
                zorder=8,
            )
            name = " ".join(
                item
                for item in (marker.id, marker.name)
                if item
            )
            label = (
                f"{name}\n"
                f"{marker.valid_at:%m/%d %H%MZ}"
            )
            axis.annotate(
                label,
                (marker.longitude, marker.latitude),
                xytext=(-7, 10),
                textcoords="offset points",
                ha="right",
                va="bottom",
                fontsize=7.5,
                fontweight="bold",
                fontproperties=font,
                color="#8f3029",
                zorder=9,
            )
            continue
        is_high = marker.kind == "high-pressure"
        centre_label = axis.text(
            marker.longitude,
            marker.latitude,
            "H" if is_high else "L",
            ha="center",
            va="center",
            fontsize=18,
            fontweight=850,
            fontproperties=font,
            color="#9b493c" if is_high else "#245a8d",
            zorder=8,
        )
        centre_label.set_path_effects(
            [
                path_effects.Stroke(linewidth=3.2, foreground="white"),
                path_effects.Normal(),
            ]
        )
        centre_value = (
            marker.central_pressure_hpa
            if marker.central_pressure_hpa is not None
            else marker.central_height_dam
        )
        if centre_value is not None:
            axis.annotate(
                f"{centre_value:.0f}",
                (marker.longitude, marker.latitude),
                xytext=(0, -12),
                textcoords="offset points",
                ha="center",
                va="top",
                fontsize=7,
                fontweight="bold",
                fontproperties=font,
                color="#9b493c" if is_high else "#245a8d",
                zorder=9,
            )


def draw_wind_barbs(
    axis: object,
    longitude: np.ndarray,
    latitude: np.ndarray,
    u_wind: np.ndarray,
    v_wind: np.ndarray,
) -> None:
    longitude_step = max(1, longitude.shape[1] // 28)
    latitude_step = max(1, latitude.shape[0] // 18)
    selection = (
        slice(None, None, latitude_step),
        slice(None, None, longitude_step),
    )
    sampled_longitude = longitude[selection]
    sampled_latitude = latitude[selection]
    sampled_u = u_wind[selection]
    sampled_v = v_wind[selection]
    sampled_speed = np.hypot(sampled_u, sampled_v)
    finite = (
        np.isfinite(sampled_longitude)
        & np.isfinite(sampled_latitude)
        & np.isfinite(sampled_u)
        & np.isfinite(sampled_v)
    )
    # Matplotlib otherwise draws an empty calm circle below the first
    # half-barb threshold. The homepage uses a compact filled point instead.
    calm = finite & (sampled_speed < 2.5)
    moving = finite & ~calm
    axis.barbs(
        sampled_longitude[moving],
        sampled_latitude[moving],
        sampled_u[moving],
        sampled_v[moving],
        color="#747b79",
        linewidth=0.36,
        length=4.0,
        alpha=0.48,
    )
    axis.scatter(
        sampled_longitude[calm],
        sampled_latitude[calm],
        s=1.7,
        marker="o",
        color="#929997",
        linewidths=0,
        alpha=0.72,
        zorder=4.2,
    )


def add_weather_colorbar(
    figure: object,
    shaded: object,
    label: str,
) -> None:
    colorbar_axis = figure.add_axes(COLORBAR_FIGURE_BOUNDS)
    colorbar = figure.colorbar(shaded, cax=colorbar_axis)
    colorbar.set_label(label, fontsize=8)
    colorbar.ax.tick_params(labelsize=7.5)


def require_field(grid: WeatherGrid, name: str) -> np.ndarray:
    try:
        return grid.fields[name]
    except KeyError as exc:
        raise ValueError(f"Weather field is unavailable: {name}") from exc


def round_up(value: float, interval: float) -> float:
    return float(np.ceil(value / interval) * interval)
