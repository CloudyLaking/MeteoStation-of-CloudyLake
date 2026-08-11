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
from matplotlib.ticker import FuncFormatter, MaxNLocator
from scipy.ndimage import maximum_filter, minimum_filter

from .analysis import (
    detect_height_axes,
    detect_surface_fronts,
    smooth_field,
)
from .basemap import LocalBoundaryLayer, TiandituBasemap
from .fields import WeatherGrid
from .models import (
    CycloneMarker,
    SynopticFeature,
    WeatherMapDomain,
    WeatherMapPreview,
)


WIND_COLORS = LinearSegmentedColormap.from_list(
    "cloudylake-wind",
    ["#ffffff", "#e8f4f4", "#c2e3e1", "#f7e8a5", "#5ba99f", "#126e68"],
)
HUMIDITY_COLORS = LinearSegmentedColormap.from_list(
    "cloudylake-humidity",
    ["#356ea6", "#b9d7e4", "#ffffff", "#f8edbd", "#9bc9bd", "#16867b"],
)
HEIGHT_ANOMALY_COLORS = LinearSegmentedColormap.from_list(
    "cloudylake-height-anomaly",
    [
        "#2f67a2",
        "#9dc9dc",
        "#e8f3f4",
        "#ffffff",
        "#fff4c7",
        "#f4d66d",
        "#c69a1b",
    ],
)
FIGURE_SIZE_INCHES = (12.0, 8.5)
MAP_FIGURE_BOUNDS = {
    "left": 0.075,
    "right": 0.860,
    "bottom": 0.100,
    "top": 0.860,
}
COLORBAR_FIGURE_BOUNDS = [0.885, 0.115, 0.017, 0.730]
SMOOTHING_SIGMA_GRIDPOINTS = {
    "surface_mslp": 3.60,
    "surface_wind_speed": 2.30,
    "850_humidity": 3.00,
    "850_height": 2.50,
    "500_height_anomaly": 3.00,
    "500_height": 2.50,
    "200_wind_speed": 2.60,
    "200_height": 2.50,
}


def render_weather_map_preview(
    grid: WeatherGrid,
    *,
    layer_id: str,
    domain: WeatherMapDomain,
    preview_root: Path,
    font_path: Path | None = None,
    cyclone_markers: list[CycloneMarker] | None = None,
    synoptic_features: list[SynopticFeature] | None = None,
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
        title = "Surface · MSLP / 10 m Wind / Features"
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
        title = "850 hPa · Humidity / Height / Wind"
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
        title = "500 hPa · Height Anomaly / Height / Wind"
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
        title = "200 hPa · Wind / Height"
    else:
        plt.close(figure)
        raise ValueError(f"Unsupported weather-map preview layer: {layer_id}")

    # Lock the published domain before selecting annotations. Contour artists
    # are decoded on a slightly larger retrieval area; using their temporary
    # autoscale limits used to admit labels that were clipped at the final
    # China-domain edge.
    axis.set_xlim(domain.west, domain.east)
    axis.set_ylim(domain.south, domain.north)

    diagnosed_features = synoptic_features
    if diagnosed_features is None:
        if layer_id in {"surface", "composite"}:
            diagnosed_features = detect_surface_fronts(
                subset,
                domain=domain,
            )
        elif layer_id == "500":
            diagnosed_features = detect_height_axes(
                subset,
                domain=domain,
                pressure_hpa=500,
            )
        else:
            diagnosed_features = []
    draw_synoptic_features(
        axis,
        diagnosed_features,
        font=font,
    )

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
    # At the domain midpoint, one degree of longitude is about cos(latitude)
    # times one degree of latitude. This keeps China from looking either
    # vertically squeezed or unnaturally narrow.
    central_latitude = (domain.south + domain.north) / 2
    axis.set_aspect(
        1 / np.cos(np.radians(central_latitude)),
        adjustable="box",
    )
    axis.set_facecolor("#ffffff")
    axis.set_xlabel("")
    axis.set_ylabel("")
    axis.xaxis.set_major_formatter(
        FuncFormatter(lambda value, _: f"{value:.0f}°E")
    )
    axis.yaxis.set_major_formatter(
        FuncFormatter(lambda value, _: f"{value:.0f}°N")
    )
    axis.xaxis.set_major_locator(MaxNLocator(nbins=9, integer=True))
    axis.yaxis.set_major_locator(MaxNLocator(nbins=8, integer=True))
    axis.tick_params(
        labelsize=10.2,
        colors="#31464d",
        length=3.2,
        width=0.7,
        direction="out",
    )
    axis.grid(
        color="#728b8b",
        linestyle="--",
        linewidth=0.42,
        alpha=0.20,
    )
    for spine in axis.spines.values():
        spine.set_color("#264b4a")
        spine.set_linewidth(0.85)
    axis.set_title(
        f"{title}\n{subset.valid_at:%Y-%m-%d %H:00 UTC}",
        loc="left",
        fontsize=17,
        fontweight=650,
        fontproperties=font,
        color="#263943",
        linespacing=1.35,
        pad=14,
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
        fontsize=9.5,
        color="#607176",
        fontproperties=font,
    )
    figure.text(
        MAP_FIGURE_BOUNDS["right"],
        0.955,
        "@CloudyLake",
        ha="right",
        va="top",
        fontsize=11,
        fontweight=700,
        color="#126e68",
        fontproperties=font,
    )

    # Preserving the geographic aspect ratio can shrink the axes inside the
    # requested subplot rectangle. Persist the actual plot box so browser
    # overlays use the identical geographic frame instead of guessed margins.
    figure.canvas.draw()
    plot_position = axis.get_position()
    plot_bounds_fraction = {
        "left": float(plot_position.x0),
        "right": float(plot_position.x1),
        "bottom": float(plot_position.y0),
        "top": float(plot_position.y1),
    }

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
            "projection": "plate-carree",
            "plot_bounds_fraction": plot_bounds_fraction,
            "height_contour_unit": "dagpm",
            "smoothing_sigma_gridpoints": (
                SMOOTHING_SIGMA_GRIDPOINTS
            ),
            "cyclone_markers": [
                marker.model_dump(mode="json")
                for marker in (cyclone_markers or [])
            ],
            "synoptic_features": [
                feature.model_dump(mode="json")
                for feature in diagnosed_features
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


def draw_synoptic_features(
    axis: object,
    features: list[SynopticFeature],
    *,
    font: FontProperties | None,
) -> None:
    """Draw objective fronts and upper-air axes with restrained symbology."""
    styles = {
        "cold-front": ("#1769aa", "-", "COLD FRONT"),
        "warm-front": ("#d6a313", "-", "WARM FRONT"),
        "stationary-front": ("#147f78", "-", "STNRY FRONT"),
        "trough-axis": ("#1769aa", "--", "TROUGH"),
        "ridge-axis": ("#d6a313", "--", "RIDGE"),
    }
    x_min, x_max = sorted(axis.get_xlim())
    y_min, y_max = sorted(axis.get_ylim())
    visible_features: list[SynopticFeature] = []
    for kind in styles:
        candidates = [
            item
            for item in features
            if item.kind == kind
            and _synoptic_feature_midpoint_inside(
                item,
                x_min=x_min + 2.5,
                x_max=x_max - 2.5,
                y_min=y_min + 2.0,
                y_max=y_max - 2.0,
            )
        ]
        if not candidates:
            continue
        high_confidence = [
            item for item in candidates if item.confidence == "high"
        ]
        pool = high_confidence or candidates
        pool.sort(
            key=lambda item: _synoptic_feature_length(item),
            reverse=True,
        )
        # A homepage background should expose the dominant systems without
        # turning every objective candidate into an annotation.
        limit = 2 if kind in {"trough-axis", "ridge-axis"} else 1
        visible_features.extend(pool[:limit])

    for feature in visible_features:
        coordinates = np.asarray(feature.coordinates, dtype=float)
        if coordinates.ndim != 2 or len(coordinates) < 2:
            continue
        color, linestyle, label = styles[feature.kind]
        alpha = 0.95 if feature.confidence == "high" else 0.78
        linewidth = 1.55 if feature.confidence == "high" else 1.15
        longitude = coordinates[:, 0]
        latitude = coordinates[:, 1]
        if feature.kind == "stationary-front":
            for index in range(len(coordinates) - 1):
                axis.plot(
                    longitude[index:index + 2],
                    latitude[index:index + 2],
                    color=("#1769aa" if index % 2 == 0 else "#d6a313"),
                    linewidth=linewidth,
                    alpha=alpha,
                    solid_capstyle="round",
                    zorder=7.0,
                )
        else:
            line = axis.plot(
                longitude,
                latitude,
                color=color,
                linestyle=linestyle,
                linewidth=linewidth,
                alpha=alpha,
                solid_capstyle="round",
                zorder=7.0,
            )[0]
            line.set_path_effects(
                [
                    path_effects.Stroke(
                        linewidth=linewidth + 1.15,
                        foreground="white",
                        alpha=0.72,
                    ),
                    path_effects.Normal(),
                ]
            )

        if feature.kind == "cold-front":
            _draw_front_symbols(
                axis,
                coordinates,
                marker="triangle",
                color=color,
                alpha=alpha,
            )
        elif feature.kind == "warm-front":
            _draw_front_symbols(
                axis,
                coordinates,
                marker="circle",
                color=color,
                alpha=alpha,
            )

        midpoint_index = len(coordinates) // 2
        text = axis.text(
            longitude[midpoint_index],
            latitude[midpoint_index],
            label,
            ha="center",
            va="bottom",
            fontsize=9.5,
            fontweight="bold",
            color=color,
            fontproperties=font,
            zorder=7.5,
        )
        text.set_path_effects(
            [
                path_effects.Stroke(linewidth=2.2, foreground="white"),
                path_effects.Normal(),
            ]
        )


def _synoptic_feature_length(feature: SynopticFeature) -> float:
    coordinates = np.asarray(feature.coordinates, dtype=float)
    if coordinates.ndim != 2 or len(coordinates) < 2:
        return 0.0
    differences = np.diff(coordinates[:, :2], axis=0)
    return float(np.nansum(np.hypot(differences[:, 0], differences[:, 1])))


def _synoptic_feature_midpoint_inside(
    feature: SynopticFeature,
    *,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> bool:
    coordinates = np.asarray(feature.coordinates, dtype=float)
    if coordinates.ndim != 2 or len(coordinates) < 2:
        return False
    longitude, latitude = coordinates[len(coordinates) // 2, :2]
    return bool(x_min <= longitude <= x_max and y_min <= latitude <= y_max)


def _draw_front_symbols(
    axis: object,
    coordinates: np.ndarray,
    *,
    marker: str,
    color: str,
    alpha: float,
) -> None:
    if len(coordinates) < 5:
        return
    stride = max(4, len(coordinates) // 7)
    indices = range(2, len(coordinates) - 1, stride)
    for index in indices:
        longitude, latitude = coordinates[index]
        if marker == "circle":
            axis.scatter(
                [longitude],
                [latitude],
                s=12,
                marker="o",
                facecolor=color,
                edgecolor="white",
                linewidth=0.35,
                alpha=alpha,
                zorder=7.3,
            )
            continue
        previous = coordinates[index - 1]
        following = coordinates[index + 1]
        tangent_angle = np.degrees(
            np.arctan2(
                following[1] - previous[1],
                following[0] - previous[0],
            )
        )
        axis.scatter(
            [longitude],
            [latitude],
            s=19,
            marker=(3, 0, tangent_angle - 90),
            facecolor=color,
            edgecolor="white",
            linewidth=0.35,
            alpha=alpha,
            zorder=7.3,
        )


def draw_local_boundaries(
    axis: object,
    boundary_layer: LocalBoundaryLayer,
) -> None:
    province_collection = LineCollection(
        boundary_layer.province_lines,
        colors="#54746f",
        linewidths=0.52,
        alpha=0.82,
        zorder=6.5,
    )
    province_collection.set_clip_on(True)
    axis.add_collection(province_collection)
    boundary_collection = LineCollection(
        boundary_layer.boundary_lines,
        colors="#163f3c",
        linewidths=1.18,
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
    inset = figure.add_axes([0.727, 0.132, 0.105, 0.195])
    inset.set_facecolor("#ffffff")
    province_collection = LineCollection(
        boundary_layer.province_lines,
        colors="#5d7b76",
        linewidths=0.42,
        alpha=0.82,
        zorder=2,
    )
    boundary_collection = LineCollection(
        boundary_layer.boundary_lines,
        colors="#163f3c",
        linewidths=0.82,
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
        spine.set_linewidth(0.72)
    inset.set_title(
        "SOUTH CHINA SEA",
        fontsize=7.5,
        fontweight=650,
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
        levels=np.linspace(0, maximum, 13),
        cmap=WIND_COLORS,
        extend="max",
        alpha=0.52,
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
        colors="#243e44",
        linewidths=0.68,
        alpha=0.86,
    )
    contour_labels = axis.clabel(
        contours,
        inline=True,
        inline_spacing=4,
        fontsize=9.8,
        fmt="%.0f",
    )
    style_contour_labels(contour_labels)
    draw_wind_barbs(axis, longitude, latitude, u_wind, v_wind)
    draw_surface_objective_features(
        axis,
        longitude,
        latitude,
        grid,
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
) -> None:
    """Overlay temperature extrema and objectively diagnosed moist zones."""
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
            alpha=0.075,
            zorder=2.6,
        )
        wet_outline = axis.contour(
            longitude,
            latitude,
            water_vapour,
            levels=[wet_threshold],
            colors="#168a7c",
            linewidths=0.64,
            linestyles="--",
            alpha=0.68,
            zorder=4.8,
        )
        axis.clabel(wet_outline, fmt={wet_threshold: "MOIST"}, fontsize=9.2)

    _draw_temperature_extrema(axis, longitude, latitude, temperature)


def _draw_temperature_extrema(
    axis: object,
    longitude: np.ndarray,
    latitude: np.ndarray,
    temperature: np.ndarray,
) -> None:
    x_min, x_max = sorted(axis.get_xlim())
    y_min, y_max = sorted(axis.get_ylim())
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
        (high_candidates, "HOT", "#b77900", True),
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
            if not (
                x_min + 2.5 <= marker_longitude <= x_max - 2.5
                and y_min + 2.0 <= marker_latitude <= y_max - 2.0
            ):
                continue
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
                fontsize=10,
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
            if count >= 1:
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
            alpha=0.50,
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
            levels=np.linspace(-maximum, maximum, 13),
            cmap=HEIGHT_ANOMALY_COLORS,
            extend="both",
            alpha=0.54,
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
            levels=np.linspace(0, maximum, 13),
            cmap=WIND_COLORS,
            extend="max",
            alpha=0.52,
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
        colors="#243e44",
        linewidths=0.68,
        alpha=0.84,
    )
    # Match the pressure-level station model convention: 588 dagpm instead
    # of 5880 gpm. The decoded field remains in geopotential metres.
    contour_labels = axis.clabel(
        contours,
        inline=True,
        inline_spacing=4,
        fontsize=9.8,
        fmt=format_geopotential_height_dagpm,
    )
    style_contour_labels(contour_labels)
    draw_wind_barbs(axis, longitude, latitude, u_wind, v_wind)
    add_weather_colorbar(figure, shaded, colorbar_label)


def draw_cyclone_markers(
    axis: object,
    markers: list[CycloneMarker],
    *,
    font: FontProperties | None,
) -> None:
    x_min, x_max = sorted(axis.get_xlim())
    y_min, y_max = sorted(axis.get_ylim())
    tropical_markers = [
        marker
        for marker in markers
        if marker.kind == "tropical"
        and x_min <= marker.longitude <= x_max
        and y_min <= marker.latitude <= y_max
    ]
    visible_markers: list[CycloneMarker] = []
    for kind in ("low-pressure", "high-pressure"):
        candidates = [
            marker
            for marker in markers
            if marker.kind == kind
            and x_min + 2.0 <= marker.longitude <= x_max - 2.0
            and y_min + 2.0 <= marker.latitude <= y_max - 2.0
        ]
        high_confidence = [
            marker for marker in candidates if marker.confidence == "high"
        ]
        pool = high_confidence or candidates
        reverse = kind == "high-pressure"
        pool.sort(
            key=lambda marker: (
                marker.central_pressure_hpa
                if marker.central_pressure_hpa is not None
                else marker.central_height_dam or 0.0
            ),
            reverse=reverse,
        )
        visible_markers.extend(pool[:2])

    for marker in [*tropical_markers, *visible_markers]:
        if marker.kind == "tropical":
            axis.scatter(
                [marker.longitude],
                [marker.latitude],
                marker="x",
                s=74,
                linewidths=1.8,
                color="#126e68",
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
                fontsize=10,
                fontweight="bold",
                fontproperties=font,
                color="#126e68",
                zorder=9,
            )
            continue
        is_high = marker.kind == "high-pressure"
        centre_color = "#ad7d00" if is_high else "#245a8d"
        centre_label = axis.text(
            marker.longitude,
            marker.latitude,
            "H" if is_high else "L",
            ha="center",
            va="center",
            fontsize=19,
            fontweight=850,
            fontproperties=font,
            color=centre_color,
            zorder=8,
        )
        centre_label.set_path_effects(
            [
                path_effects.Stroke(linewidth=2.8, foreground="white"),
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
                fontsize=9.5,
                fontweight="bold",
                fontproperties=font,
                color=centre_color,
                zorder=9,
            )


def draw_wind_barbs(
    axis: object,
    longitude: np.ndarray,
    latitude: np.ndarray,
    u_wind: np.ndarray,
    v_wind: np.ndarray,
) -> None:
    longitude_step = max(1, longitude.shape[1] // 25)
    latitude_step = max(1, latitude.shape[0] // 16)
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
        color="#667c7a",
        linewidth=0.34,
        length=3.8,
        alpha=0.36,
    )
    axis.scatter(
        sampled_longitude[calm],
        sampled_latitude[calm],
        s=1.7,
        marker="o",
        color="#8d9b99",
        linewidths=0,
        alpha=0.58,
        zorder=4.2,
    )


def add_weather_colorbar(
    figure: object,
    shaded: object,
    label: str,
) -> None:
    colorbar_axis = figure.add_axes(COLORBAR_FIGURE_BOUNDS)
    colorbar = figure.colorbar(shaded, cax=colorbar_axis)
    colorbar.locator = MaxNLocator(
        nbins=6,
        steps=[1, 2, 2.5, 5, 10],
    )
    colorbar.update_ticks()
    colorbar.ax.yaxis.set_major_formatter(
        FuncFormatter(lambda value, _: f"{value:g}")
    )
    colorbar.set_label(label, fontsize=10.5, color="#31464d", labelpad=9)
    colorbar.ax.tick_params(
        labelsize=9.8,
        colors="#31464d",
        length=3,
        width=0.65,
    )
    colorbar.outline.set_linewidth(0.7)
    colorbar.outline.set_edgecolor("#31464d")


def style_contour_labels(labels: list[object]) -> None:
    """Keep contour values legible without opaque boxes or heavy halos."""
    for label in labels:
        label.set_color("#243e44")
        label.set_path_effects(
            [
                path_effects.Stroke(
                    linewidth=1.65,
                    foreground="white",
                    alpha=0.88,
                ),
                path_effects.Normal(),
            ]
        )


def require_field(grid: WeatherGrid, name: str) -> np.ndarray:
    try:
        return grid.fields[name]
    except KeyError as exc:
        raise ValueError(f"Weather field is unavailable: {name}") from exc


def round_up(value: float, interval: float) -> float:
    return float(np.ceil(value / interval) * interval)


def format_geopotential_height_dagpm(value: float) -> str:
    """Format a geopotential-metre contour in decametres."""
    return f"{value / 10:.0f}"
