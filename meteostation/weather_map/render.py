from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
import numpy as np
from PIL import Image
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.font_manager import FontProperties, fontManager
from matplotlib.collections import LineCollection
from matplotlib.offsetbox import AnnotationBbox, DrawingArea
from matplotlib.patches import Arc, Circle
from matplotlib.ticker import FuncFormatter, MaxNLocator
from scipy.ndimage import maximum_filter, minimum_filter

from .analysis import (
    detect_height_axes,
    detect_high_pressure_centres,
    detect_low_pressure_centres,
    detect_pressure_level_centres,
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
    ["#f8faf9", "#d9eceb", "#91c8c3", "#f1d993", "#d58b63", "#a2544c", "#71537f"],
)
TEMPERATURE_COLORS = LinearSegmentedColormap.from_list(
    "cloudylake-temperature",
    ["#5d4b78", "#7b88b5", "#d8e2e1", "#f7f5f1", "#e7c39e", "#c8795d", "#964b46"],
)
HUMIDITY_COLORS = LinearSegmentedColormap.from_list(
    "cloudylake-humidity",
    ["#9b765e", "#d6c1ad", "#f6f3ed", "#c8dfda", "#68aaa2", "#126e68"],
)
HEIGHT_ANOMALY_COLORS = LinearSegmentedColormap.from_list(
    "cloudylake-height-anomaly",
    [
        "#5d4b78",
        "#998aae",
        "#d8d0df",
        "#f7f5f1",
        "#edcfb7",
        "#c8795d",
        "#964b46",
    ],
)
FIGURE_SIZE_INCHES = (15.0, 10.0)
MAP_FIGURE_BOUNDS = {
    "left": 0.052,
    "right": 0.895,
    "bottom": 0.082,
    "top": 0.875,
}
COLORBAR_FIGURE_BOUNDS = [0.920, 0.105, 0.016, 0.748]
SMOOTHING_SIGMA_GRIDPOINTS = {
    "surface_mslp": 3.60,
    "surface_wind_speed": 2.30,
    "850_humidity": 3.00,
    "850_temperature_anomaly": 2.20,
    "850_height": 2.50,
    "500_height_anomaly": 3.00,
    "500_height": 2.50,
    "200_wind_speed": 2.60,
    "200_height": 2.50,
}
TYPE_SIZE = {
    "title": 17.0,
    "tick": 17.0,
    "contour": 17.0,
    "annotation": 17.0,
    "cyclone": 17.0,
    "centre": 17.0,
    "centre_value": 17.0,
    "colorbar": 17.0,
    "colorbar_tick": 17.0,
    "footer": 17.0,
    "inset": 17.0,
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
    validate_weather_fields(subset, layer_id)
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
    if font is not None:
        fontManager.addfont(str(font_path))
        plt.rcParams["font.family"] = font.get_name()
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
    if layer_id == "composite":
        draw_composite(axis, figure, longitude_grid, latitude_grid, subset)
        title = "COMPOSITE | 850-hPa Temperature Anomaly & Wind / 500-hPa Geopotential Height"
    elif layer_id == "surface":
        draw_surface(axis, figure, longitude_grid, latitude_grid, subset)
        title = "SURFACE | 2-m Temperature / MSLP / 10-m Wind"
    elif layer_id == "850":
        draw_pressure_level(
            axis, figure, longitude_grid, latitude_grid, subset,
            pressure_hpa=850, shade="humidity",
        )
        title = "850 hPa | Relative Humidity / Geopotential Height / Wind"
    elif layer_id == "500":
        draw_pressure_level(
            axis, figure, longitude_grid, latitude_grid, subset,
            pressure_hpa=500, shade="height_anomaly",
        )
        title = "500 hPa | Geopotential Height Anomaly / Height / Wind"
    elif layer_id == "200":
        draw_pressure_level(
            axis, figure, longitude_grid, latitude_grid, subset,
            pressure_hpa=200, shade="wind",
        )
        title = "200 hPa | Wind Speed / Geopotential Height"
    else:
        plt.close(figure)
        raise ValueError(f"Unsupported weather-map preview layer: {layer_id}")

    # Lock the published domain before selecting annotations. Contour artists
    # are decoded on a slightly larger retrieval area; using their temporary
    # autoscale limits used to admit labels that were clipped at the final
    # China-domain edge.
    axis.set_xlim(domain.west, domain.east)
    axis.set_ylim(domain.south, domain.north)

    # Build an objective analysis layer from the same valid-time background.
    # Explicit caller-supplied features still take precedence for reviewed
    # products and tests.
    if synoptic_features is not None:
        diagnosed_features = synoptic_features
    elif layer_id == "surface":
        diagnosed_features = detect_surface_fronts(subset, domain=domain)
    elif layer_id in {"composite", "500"}:
        diagnosed_features = detect_height_axes(
            subset,
            domain=domain,
            pressure_hpa=500,
        )
    else:
        diagnosed_features = []
    tropical_markers = [
        marker
        for marker in (cyclone_markers or [])
        if marker.kind == "tropical"
    ]
    diagnosed_features = [
        feature
        for feature in diagnosed_features
        if not _feature_near_tropical_cyclone(
            feature,
            tropical_markers,
            radius_degrees=(8.0 if "front" in feature.kind else 6.0),
        )
    ]
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
            axis,
            boundary_layer,
            font=font,
        )
    objective_centres: list[CycloneMarker]
    if layer_id == "surface":
        objective_centres = [
            *detect_low_pressure_centres(subset, domain=domain),
            *detect_high_pressure_centres(subset, domain=domain),
        ]
    else:
        centre_level = 500 if layer_id == "composite" else int(layer_id)
        objective_centres = detect_pressure_level_centres(
            subset,
            domain=domain,
            pressure_hpa=centre_level,
        )
    objective_centres = [
        marker
        for marker in objective_centres
        if not any(
            np.hypot(
                marker.latitude - tropical.latitude,
                marker.longitude - tropical.longitude,
            ) < 6.0
            for tropical in tropical_markers
        )
    ]
    analysed_markers = [*tropical_markers, *objective_centres]
    draw_cyclone_markers(axis, analysed_markers, font=font)
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
        labelsize=TYPE_SIZE["tick"],
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
        spine.set_linewidth(0.55)
    axis.set_title(
        f"{title}  |  {subset.valid_at:%Y-%m-%d %H:00 UTC}",
        loc="left",
        fontsize=TYPE_SIZE["title"],
        fontweight=700,
        fontproperties=font,
        color="#263943",
        pad=12,
    )
    source_note = subset.source
    if layer_id in {"composite", "500"}:
        normal_metadata = subset.metadata.get("height_climatology_500", {})
        if isinstance(normal_metadata, dict):
            normal_period = normal_metadata.get("normal_period", "1991-2020")
            source_note += f" | ERA5 {normal_period} monthly normals"
    figure.text(
        MAP_FIGURE_BOUNDS["left"],
        0.026,
        f"Source: {source_note} | meteostation.top",
        fontsize=TYPE_SIZE["footer"],
        color="#607176",
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
    image_path = directory / f"{stem}.webp"
    metadata_path = directory / f"{stem}.json"
    temporary_png = directory / f".{stem}.png.tmp"
    temporary_image = directory / f".{stem}.webp.tmp"
    figure.savefig(
        temporary_png,
        format="png",
        dpi=180,
        facecolor="white",
    )
    plt.close(figure)
    with Image.open(temporary_png) as source_image:
        source_image.convert("RGB").save(
            temporary_image,
            format="WEBP",
            quality=92,
            method=6,
        )
    temporary_png.unlink(missing_ok=True)
    os.replace(temporary_image, image_path)
    (directory / f"{stem}.png").unlink(missing_ok=True)
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
                for marker in analysed_markers
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
        "stationary-front": ("#147f78", "-", "STATIONARY FRONT"),
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
            fontsize=TYPE_SIZE["annotation"],
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


def _feature_near_tropical_cyclone(
    feature: SynopticFeature,
    tropical_markers: list[CycloneMarker],
    *,
    radius_degrees: float,
) -> bool:
    """Suppress objective axes that duplicate an authoritative TC analysis."""
    coordinates = np.asarray(feature.coordinates, dtype=float)
    if coordinates.ndim != 2 or not len(coordinates):
        return False
    for marker in tropical_markers:
        distance = np.hypot(
            coordinates[:, 1] - marker.latitude,
            coordinates[:, 0] - marker.longitude,
        )
        if float(np.nanmin(distance)) < radius_degrees:
            return True
    return False


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
    axis: object,
    boundary_layer: LocalBoundaryLayer,
    *,
    font: FontProperties | None,
) -> None:
    """Draw the South China Sea inset over the low-information India corner."""
    inset = axis.inset_axes([0.025, 0.045, 0.155, 0.285], zorder=7.5)
    inset.set_facecolor((1, 1, 1, 0.94))
    inset.add_collection(LineCollection(
        boundary_layer.province_lines,
        colors="#5d7b76", linewidths=0.55, alpha=0.88, zorder=2,
    ))
    inset.add_collection(LineCollection(
        boundary_layer.boundary_lines,
        colors="#163f3c", linewidths=0.95, alpha=1.0, zorder=3,
    ))
    inset.set_xlim(105, 125)
    inset.set_ylim(3, 25)
    inset.set_aspect(1 / np.cos(np.radians(14)), adjustable="box")
    inset.set_xticks([])
    inset.set_yticks([])
    inset.tick_params(length=0)
    for spine in inset.spines.values():
        spine.set_color("#41645f")
        spine.set_linewidth(0.65)
    inset.set_title(
        "SOUTH CHINA SEA",
        fontsize=TYPE_SIZE["inset"],
        fontweight=700,
        fontproperties=font,
        color="#41645f",
        pad=3,
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
    temperature = smooth_field(
        require_field(grid, "temperature_2m_c"),
        sigma_gridpoints=2.0,
    )
    lower = np.floor(np.nanpercentile(temperature, 1) / 2) * 2
    upper = np.ceil(np.nanpercentile(temperature, 99) / 2) * 2
    if upper <= lower:
        upper = lower + 2
    shaded = axis.contourf(
        longitude,
        latitude,
        temperature,
        levels=np.arange(lower, upper + 2.1, 2),
        cmap=TEMPERATURE_COLORS,
        extend="both",
        alpha=0.78,
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
        linewidths=0.82,
        alpha=0.86,
    )
    contour_labels = axis.clabel(
        contours,
        inline=True,
        inline_spacing=4,
        fontsize=TYPE_SIZE["contour"],
        fmt="%.0f",
    )
    style_contour_labels(contour_labels)
    draw_wind_barbs(axis, longitude, latitude, u_wind, v_wind)
    add_weather_colorbar(
        figure,
        shaded,
        "2-m Temperature (°C)",
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
        axis.clabel(
            wet_outline,
            fmt={wet_threshold: "MOIST"},
            fontsize=TYPE_SIZE["annotation"],
        )

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
        (high_candidates, "WARM", "#a95c38", True),
        (low_candidates, "COLD", "#516591", False),
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
                fontsize=TYPE_SIZE["annotation"],
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


def draw_composite(
    axis: object,
    figure: object,
    longitude: np.ndarray,
    latitude: np.ndarray,
    grid: WeatherGrid,
) -> None:
    """850-hPa temperature anomaly and wind with 500-hPa height contours."""
    temperature = require_field(grid, "temperature_850_c")
    normal = require_field(grid, "temperature_850_climatology_c")
    anomaly = smooth_field(
        temperature - normal,
        sigma_gridpoints=SMOOTHING_SIGMA_GRIDPOINTS["850_temperature_anomaly"],
    )
    maximum = max(
        4,
        round_up(float(np.nanpercentile(np.abs(anomaly), 99)), 2),
    )
    shaded = axis.contourf(
        longitude,
        latitude,
        anomaly,
        levels=np.arange(-maximum, maximum + 0.1, 2),
        cmap=HEIGHT_ANOMALY_COLORS,
        extend="both",
        alpha=0.80,
        zorder=1,
    )
    height = smooth_field(
        require_field(grid, "geopotential_height_500_gpm"),
        sigma_gridpoints=SMOOTHING_SIGMA_GRIDPOINTS["500_height"],
    )
    height_interval = 40
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
        colors="#1f343a",
        linewidths=1.05,
        alpha=0.94,
        zorder=3.4,
    )
    contour_labels = axis.clabel(
        contours,
        inline=True,
        inline_spacing=5,
        fontsize=TYPE_SIZE["contour"],
        fmt=format_geopotential_height_dagpm,
    )
    style_contour_labels(contour_labels)
    draw_wind_barbs(
        axis,
        longitude,
        latitude,
        require_field(grid, "wind_u_850_ms"),
        require_field(grid, "wind_v_850_ms"),
    )
    add_weather_colorbar(figure, shaded, "850-hPa Temperature Anomaly (°C)")


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
    height = require_field(grid, f"geopotential_height_{suffix}_gpm")
    u_wind = require_field(grid, f"wind_u_{suffix}_ms")
    v_wind = require_field(grid, f"wind_v_{suffix}_ms")
    if shade == "humidity":
        shaded_values = smooth_field(
            require_field(grid, f"relative_humidity_{suffix}_pct"),
            sigma_gridpoints=SMOOTHING_SIGMA_GRIDPOINTS["850_humidity"],
        )
        shaded = axis.contourf(
            longitude, latitude, shaded_values,
            levels=np.arange(10, 101, 10), cmap=HUMIDITY_COLORS,
            extend="both", alpha=0.74,
        )
        colorbar_label = "Relative Humidity (%)"
    elif shade == "height_anomaly":
        climatology_height = require_field(
            grid, "geopotential_height_500_climatology_gpm"
        )
        shaded_values = smooth_field(
            height - climatology_height,
            sigma_gridpoints=SMOOTHING_SIGMA_GRIDPOINTS["500_height_anomaly"],
        )
        maximum = max(
            40,
            round_up(float(np.nanpercentile(np.abs(shaded_values), 98)), 20),
        )
        shaded = axis.contourf(
            longitude, latitude, shaded_values,
            levels=np.linspace(-maximum, maximum, 13),
            cmap=HEIGHT_ANOMALY_COLORS, extend="both", alpha=0.76,
        )
        colorbar_label = "500-hPa Geopotential Height Anomaly (gpm)"
    else:
        shaded_values = smooth_field(
            np.hypot(u_wind, v_wind),
            sigma_gridpoints=SMOOTHING_SIGMA_GRIDPOINTS["200_wind_speed"],
        )
        maximum = max(30, round_up(float(np.nanpercentile(shaded_values, 99)), 5))
        shaded = axis.contourf(
            longitude, latitude, shaded_values,
            levels=np.linspace(0, maximum, 13), cmap=WIND_COLORS,
            extend="max", alpha=0.76,
        )
        colorbar_label = f"{pressure_hpa}-hPa Wind Speed (m s⁻¹)"
    height = smooth_field(
        height,
        sigma_gridpoints=SMOOTHING_SIGMA_GRIDPOINTS[f"{pressure_hpa}_height"],
    )
    height_interval = {850: 30, 500: 40, 200: 120}[pressure_hpa]
    height_levels = np.arange(
        np.floor(np.nanmin(height) / height_interval) * height_interval,
        np.ceil(np.nanmax(height) / height_interval) * height_interval + 0.1,
        height_interval,
    )
    contours = axis.contour(
        longitude, latitude, height, levels=height_levels,
        colors="#243e44", linewidths=1.0, alpha=0.92,
    )
    contour_labels = axis.clabel(
        contours, inline=True, inline_spacing=5,
        fontsize=TYPE_SIZE["contour"], fmt=format_geopotential_height_dagpm,
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
            symbol = DrawingArea(28, 28, 0, 0)
            symbol.add_artist(Circle((14, 14), 2.8, fill=False, color="#8e3f45", lw=1.8))
            symbol.add_artist(Arc((10, 14), 17, 12, angle=0, theta1=145, theta2=348, color="#8e3f45", lw=2.0))
            symbol.add_artist(Arc((18, 14), 17, 12, angle=0, theta1=-35, theta2=168, color="#8e3f45", lw=2.0))
            axis.add_artist(AnnotationBbox(
                symbol,
                (marker.longitude, marker.latitude),
                frameon=False,
                box_alignment=(0.5, 0.5),
                zorder=8,
            ))
            name = " ".join(
                item
                for item in (marker.id, marker.name)
                if item
            )
            details = []
            if marker.central_pressure_hpa is not None:
                details.append(f"{marker.central_pressure_hpa:.0f} hPa")
            if marker.maximum_wind_ms is not None:
                details.append(f"{marker.maximum_wind_ms:.0f} m/s")
            label = f"{name}\n{marker.valid_at:%m/%d %H%MZ}"
            if details:
                label += " | " + " · ".join(details)
            label_above = marker.longitude >= 125
            annotation = axis.annotate(
                label,
                (marker.longitude, marker.latitude),
                xytext=(-8 if label_above else 8, 16 if label_above else -2),
                textcoords="offset points",
                ha="right" if label_above else "left",
                va="bottom" if label_above else "top",
                fontsize=TYPE_SIZE["cyclone"],
                fontweight="bold",
                fontproperties=font,
                color="#8e3f45",
                zorder=9,
            )
            annotation.set_path_effects(
                [
                    path_effects.Stroke(
                        linewidth=2.2,
                        foreground="white",
                        alpha=0.92,
                    ),
                    path_effects.Normal(),
                ]
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
            fontsize=TYPE_SIZE["centre"],
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
                fontsize=TYPE_SIZE["centre_value"],
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
    longitude_step = max(1, longitude.shape[1] // 27)
    latitude_step = max(1, latitude.shape[0] // 17)
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
        color="#435d5b",
        linewidth=0.52,
        length=4.5,
        alpha=0.72,
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
    colorbar.set_label(
        label,
        fontsize=TYPE_SIZE["colorbar"],
        color="#31464d",
        labelpad=12,
    )
    colorbar.ax.tick_params(
        labelsize=TYPE_SIZE["colorbar_tick"],
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


def validate_weather_fields(grid: WeatherGrid, layer_id: str) -> None:
    """Reject missing, non-finite or physically implausible chart inputs."""
    required: dict[str, tuple[float, float]] = {
        "mslp_hpa": (850, 1100),
        "temperature_2m_c": (-90, 65),
        "wind_u_10m_ms": (-100, 100),
        "wind_v_10m_ms": (-100, 100),
    }
    if layer_id == "composite":
        required = {
            "temperature_850_c": (-90, 55),
            "temperature_850_climatology_c": (-90, 55),
            "wind_u_850_ms": (-200, 200),
            "wind_v_850_ms": (-200, 200),
            "geopotential_height_500_gpm": (3500, 7000),
        }
    if layer_id in {"850", "500", "200"}:
        pressure = int(layer_id)
        required = {
            f"geopotential_height_{pressure}_gpm": {
                850: (-500, 3000), 500: (3500, 7000), 200: (8000, 15000)
            }[pressure],
            f"wind_u_{pressure}_ms": (-200, 200),
            f"wind_v_{pressure}_ms": (-200, 200),
        }
        if pressure == 850:
            required["relative_humidity_850_pct"] = (0, 105)
        elif pressure == 500:
            required["geopotential_height_500_climatology_gpm"] = (3500, 7000)
    for name, (minimum, maximum) in required.items():
        values = require_field(grid, name)
        finite = values[np.isfinite(values)]
        if finite.size < values.size * 0.9:
            raise ValueError(f"Weather field has insufficient valid coverage: {name}")
        low = float(np.nanpercentile(finite, 0.1))
        high = float(np.nanpercentile(finite, 99.9))
        if low < minimum or high > maximum:
            raise ValueError(
                f"Weather field failed physical-range validation: {name} "
                f"({low:.1f} to {high:.1f})"
            )


def round_up(value: float, interval: float) -> float:
    return float(np.ceil(value / interval) * interval)


def format_geopotential_height_dagpm(value: float) -> str:
    """Format a geopotential-metre contour in decametres."""
    return f"{value / 10:.0f}"
