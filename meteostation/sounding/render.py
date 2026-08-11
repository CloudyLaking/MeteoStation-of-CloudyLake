import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.font_manager import FontProperties, fontManager
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import ScalarFormatter
from metpy.calc import wind_components
from metpy.plots import SkewT
from metpy.units import units

from .diagnostics import calculate_sounding_diagnostics
from .models import SoundingDiagnostics, SoundingProduct, SoundingProfile


RENDERER_VERSION = "sounding-images-V2.2.1-large-type"
STANDARD_PRESSURE_LEVELS = [1000, 925, 850, 700, 500, 400, 300, 250, 200, 150, 100]
MAIN_RECT = (0.20, 0.09, 0.56, 0.83)
HUMIDITY_RECT = (0.075, 0.09, 0.052, 0.83)
WIND_RECT = (0.83, 0.09, 0.052, 0.83)
HUMIDITY_COLORS = LinearSegmentedColormap.from_list(
    "cloud_band",
    ["#f1dfc9", "#d7ded3", "#9fc8bd", "#668d98"],
)
WIND_COLORS = LinearSegmentedColormap.from_list(
    "wind_band",
    [
        "#eef2f4",
        "#9ed8ee",
        "#208dbd",
        "#18a66b",
        "#75df45",
        "#f1e84d",
        "#f0a43c",
        "#ef5c4f",
        "#e85291",
        "#cb45ce",
        "#5d388d",
    ],
)


def render_skewt_quicklook(
    profile: SoundingProfile,
    *,
    product_root: Path,
    font_path: Path | None = None,
    station_name: str | None = None,
) -> SoundingProduct:
    pressure, temperature, dewpoint = thermo_arrays(profile)
    diagnostics = calculate_sounding_diagnostics(profile)
    (
        diagnostic_pressure,
        diagnostic_temperature,
        diagnostic_dewpoint,
        virtual_temperature,
        parcel_temperature,
    ) = diagnostic_plot_arrays(profile, diagnostics)
    font_properties = load_font(font_path)
    font_options = font_kwargs(font_properties)

    figure = plt.figure(figsize=(13.5, 9.2), facecolor="white")
    skew = SkewT(
        figure,
        rotation=45,
        rect=MAIN_RECT,
        aspect="auto",
    )
    skew.ax.set_facecolor("#fffdfb")
    skew.ax.set_ylim(1050, 100)
    skew.ax.set_xlim(-70, 45)
    skew.plot(
        pressure,
        temperature,
        color="#df2727",
        linewidth=2.4,
        label="Temperature",
    )
    skew.plot(
        pressure,
        dewpoint,
        color="#287c70",
        linewidth=2.4,
        label="Dew Point",
    )
    skew.shade_cape(
        diagnostic_pressure,
        diagnostic_temperature,
        parcel_temperature,
        color="#eaa66c",
        alpha=0.24,
    )
    skew.shade_cin(
        diagnostic_pressure,
        diagnostic_temperature,
        parcel_temperature,
        dewpoint=diagnostic_dewpoint,
        color="#77a7c9",
        alpha=0.22,
    )
    skew.plot(
        diagnostic_pressure,
        virtual_temperature,
        color="#8463a6",
        linewidth=1.5,
        linestyle="--",
        label="Virtual Temperature",
    )
    skew.plot(
        diagnostic_pressure,
        parcel_temperature,
        color="#d39143",
        linewidth=1.6,
        linestyle=":",
        label="Surface Parcel",
    )
    plot_lcl_line(
        skew.ax,
        diagnostics,
        font_properties=font_properties,
    )
    skew.ax.grid(False)
    skew.ax.grid(
        axis="x",
        color="#bba999",
        alpha=0.15,
        linewidth=0.55,
    )
    skew.plot_dry_adiabats(color="#b5967f", alpha=0.09, linewidth=0.55)
    skew.plot_moist_adiabats(color="#d2909e", alpha=0.08, linewidth=0.55)
    skew.plot_mixing_lines(color="#8aa7bd", alpha=0.07, linewidth=0.55)
    skew.ax.axvline(
        0,
        color="#3c76aa",
        linestyle="--",
        linewidth=0.8,
        alpha=0.55,
    )
    configure_pressure_axis(skew.ax)
    skew.ax.set_xlabel("Temperature (°C)", color="#5f676a", **font_options)
    skew.ax.set_ylabel("Pressure (hPa)", color="#5f676a", **font_options)
    add_figure_legend(figure, font_properties=font_properties)
    add_profile_bands(
        figure,
        profile,
        font_properties=font_properties,
    )

    add_english_header(
        figure,
        profile,
        diagram_label="Skew-T",
        station_name=station_name,
        font_properties=font_properties,
        diagnostics=diagnostics,
    )
    return save_product(
        figure,
        profile,
        product_root=product_root,
        diagram_type="skewt",
        station_name=station_name,
    )


def render_stuve_quicklook(
    profile: SoundingProfile,
    *,
    product_root: Path,
    font_path: Path | None = None,
    station_name: str | None = None,
) -> SoundingProduct:
    pressure, temperature, dewpoint = thermo_arrays(profile)
    diagnostics = calculate_sounding_diagnostics(profile)
    (
        diagnostic_pressure,
        diagnostic_temperature,
        _,
        virtual_temperature,
        parcel_temperature,
    ) = diagnostic_plot_arrays(profile, diagnostics)
    font_properties = load_font(font_path)
    font_options = font_kwargs(font_properties)

    figure = plt.figure(figsize=(13.5, 9.2), facecolor="white")
    axis = figure.add_axes(MAIN_RECT)
    axis.set_facecolor("#fffdfb")
    axis.set_yscale("log")
    axis.set_ylim(1050, 100)
    axis.set_xlim(-95, 50)
    configure_pressure_axis(axis)
    axis.plot(
        temperature.magnitude,
        pressure.magnitude,
        color="#df2727",
        linewidth=2.4,
        label="Temperature",
    )
    axis.plot(
        dewpoint.magnitude,
        pressure.magnitude,
        color="#287c70",
        linewidth=2.4,
        label="Dew Point",
    )
    diagnostic_pressure_values = diagnostic_pressure.magnitude
    diagnostic_temperature_values = diagnostic_temperature.magnitude
    parcel_temperature_values = parcel_temperature.magnitude
    cape_mask = parcel_temperature_values > diagnostic_temperature_values
    cin_mask = parcel_temperature_values < diagnostic_temperature_values
    if diagnostics.lfc_pressure_hpa is not None:
        cin_mask &= (
            diagnostic_pressure_values >= diagnostics.lfc_pressure_hpa
        )
    axis.fill_betweenx(
        diagnostic_pressure_values,
        diagnostic_temperature_values,
        parcel_temperature_values,
        where=cape_mask,
        color="#eaa66c",
        alpha=0.24,
        interpolate=True,
        label="CAPE",
    )
    axis.fill_betweenx(
        diagnostic_pressure_values,
        diagnostic_temperature_values,
        parcel_temperature_values,
        where=cin_mask,
        color="#77a7c9",
        alpha=0.22,
        interpolate=True,
        label="CIN",
    )
    axis.plot(
        virtual_temperature.magnitude,
        diagnostic_pressure_values,
        color="#8463a6",
        linewidth=1.5,
        linestyle="--",
        label="Virtual Temperature",
    )
    axis.plot(
        parcel_temperature_values,
        diagnostic_pressure_values,
        color="#d39143",
        linewidth=1.6,
        linestyle=":",
        label="Surface Parcel",
    )
    plot_lcl_line(
        axis,
        diagnostics,
        font_properties=font_properties,
    )
    axis.axvline(
        0,
        color="#3c76aa",
        linestyle="--",
        linewidth=0.8,
        alpha=0.55,
    )
    axis.set_xlabel("Temperature (°C)", color="#5f676a", **font_options)
    axis.set_ylabel("Pressure (hPa)", color="#5f676a", **font_options)
    add_figure_legend(figure, font_properties=font_properties)
    add_profile_bands(
        figure,
        profile,
        font_properties=font_properties,
    )

    add_english_header(
        figure,
        profile,
        diagram_label="Stüve",
        station_name=station_name,
        font_properties=font_properties,
        diagnostics=diagnostics,
    )
    return save_product(
        figure,
        profile,
        product_root=product_root,
        diagram_type="stuve",
        station_name=station_name,
    )


def thermo_arrays(
    profile: SoundingProfile,
) -> tuple[object, object, object]:
    pressure_values: list[float] = []
    temperature_values: list[float] = []
    dewpoint_values: list[float] = []

    for level in profile.levels:
        if level.temperature_c is None or level.dewpoint_c is None:
            continue
        pressure_values.append(level.pressure_hpa)
        temperature_values.append(level.temperature_c)
        dewpoint_values.append(level.dewpoint_c)

    if len(pressure_values) < 3:
        raise ValueError("At least three temperature/dew-point levels are required")

    return (
        np.asarray(pressure_values) * units.hPa,
        np.asarray(temperature_values) * units.degC,
        np.asarray(dewpoint_values) * units.degC,
    )


def diagnostic_plot_arrays(
    profile: SoundingProfile,
    diagnostics: SoundingDiagnostics,
) -> tuple[object, object, object, object, object]:
    profile_by_pressure = {
        round(level.pressure_hpa, 3): level
        for level in profile.levels
        if level.temperature_c is not None and level.dewpoint_c is not None
    }
    diagnostic_levels = [
        level
        for level in diagnostics.levels
        if round(level.pressure_hpa, 3) in profile_by_pressure
    ]
    pressure_values = np.asarray(
        [level.pressure_hpa for level in diagnostic_levels]
    )
    source_levels = [
        profile_by_pressure[round(level.pressure_hpa, 3)]
        for level in diagnostic_levels
    ]
    return (
        pressure_values * units.hPa,
        np.asarray(
            [level.temperature_c for level in source_levels]
        ) * units.degC,
        np.asarray(
            [level.dewpoint_c for level in source_levels]
        ) * units.degC,
        np.asarray(
            [level.virtual_temperature_c for level in diagnostic_levels]
        ) * units.degC,
        np.asarray(
            [level.parcel_temperature_c for level in diagnostic_levels]
        ) * units.degC,
    )


def plot_lcl_line(
    axis: object,
    diagnostics: SoundingDiagnostics,
    *,
    font_properties: FontProperties | None,
) -> None:
    pressure = diagnostics.lcl_pressure_hpa
    if pressure is None or pressure < 100 or pressure > 1050:
        return
    axis.axhline(
        pressure,
        color="#a96d2d",
        linewidth=0.9,
        linestyle=(0, (7, 4)),
        alpha=0.78,
    )
    axis.text(
        0.985,
        pressure,
        f"LCL {pressure:.0f} hPa",
        transform=axis.get_yaxis_transform(),
        ha="right",
        va="bottom",
        color="#98612b",
        fontsize=8.5,
        fontproperties=font_properties,
    )


def wind_arrays(
    profile: SoundingProfile,
) -> tuple[object, object, object] | None:
    wind_levels = [
        level
        for level in profile.levels
        if level.wind_speed_ms is not None
        and level.wind_direction_deg is not None
        and level.pressure_hpa >= 100
    ]
    if not wind_levels:
        return None

    stride = max(1, len(wind_levels) // 28)
    selected = wind_levels[::stride]
    pressure = np.asarray([level.pressure_hpa for level in selected]) * units.hPa
    speed = np.asarray([level.wind_speed_ms for level in selected]) * units("m/s")
    direction = (
        np.asarray([level.wind_direction_deg for level in selected]) * units.degree
    )
    u_wind, v_wind = wind_components(speed, direction)
    return pressure, u_wind.to("knots"), v_wind.to("knots")


def configure_pressure_axis(axis: object) -> None:
    axis.set_yticks(STANDARD_PRESSURE_LEVELS)
    axis.yaxis.set_major_formatter(ScalarFormatter())
    axis.minorticks_off()
    axis.tick_params(axis="both", colors="#667276", labelsize=9.5)
    for level in STANDARD_PRESSURE_LEVELS:
        is_primary = level in {1000, 850, 700, 500, 300, 200, 100}
        axis.axhline(
            level,
            color="#947d6a",
            alpha=0.29 if is_primary else 0.16,
            linewidth=0.75 if is_primary else 0.5,
            zorder=0,
        )


def add_profile_bands(
    figure: object,
    profile: SoundingProfile,
    *,
    font_properties: FontProperties | None,
) -> None:
    humidity_axis = figure.add_axes(HUMIDITY_RECT)
    wind_axis = figure.add_axes(WIND_RECT)

    draw_scalar_band(
        humidity_axis,
        profile,
        attribute="relative_humidity_pct",
        value_min=0,
        value_max=100,
        color_map=HUMIDITY_COLORS,
        title="RH / CLOUD",
        tick_labels=("0", "50", "100"),
        font_properties=font_properties,
    )
    draw_scalar_band(
        wind_axis,
        profile,
        attribute="wind_speed_ms",
        value_min=0,
        value_max=50,
        color_map=WIND_COLORS,
        title="WIND m/s",
        tick_labels=("0", "25", "50+"),
        font_properties=font_properties,
    )

    arrays = wind_arrays(profile)
    if arrays is not None:
        pressure, u_wind, v_wind = arrays
        wind_axis.barbs(
            np.full(len(pressure), 0.50),
            pressure.magnitude,
            u_wind.magnitude,
            v_wind.magnitude,
            color="#334e60",
            linewidth=0.42,
            length=4.0,
            alpha=0.78,
        )


def draw_scalar_band(
    axis: object,
    profile: SoundingProfile,
    *,
    attribute: str,
    value_min: float,
    value_max: float,
    color_map: LinearSegmentedColormap,
    title: str,
    tick_labels: tuple[str, str, str],
    font_properties: FontProperties | None,
) -> None:
    values = [
        (level.pressure_hpa, getattr(level, attribute))
        for level in profile.levels
        if getattr(level, attribute) is not None and level.pressure_hpa >= 100
    ]
    axis.set_yscale("log")
    axis.set_ylim(1050, 100)
    axis.set_xlim(0, 1)
    axis.set_facecolor("#f8f4ef")
    axis.set_yticks(STANDARD_PRESSURE_LEVELS)
    axis.set_yticklabels([])
    axis.minorticks_off()
    axis.tick_params(axis="y", length=0)
    axis.set_xticks([0, 0.5, 1])
    axis.set_xticklabels(tick_labels, fontsize=7.5, color="#748084")
    axis.set_title(
        title,
        color="#5f6e72",
        fontsize=8.5,
        pad=6,
        fontproperties=font_properties,
    )

    for spine in axis.spines.values():
        spine.set_color("#c9b9aa")
        spine.set_linewidth(0.6)

    if not values:
        return

    pressure = np.asarray([item[0] for item in values])
    scalar = np.asarray([item[1] for item in values], dtype=float)
    norm = Normalize(value_min, value_max, clip=True)

    upper_bounds = np.concatenate(
        ([1050.0], np.sqrt(pressure[:-1] * pressure[1:]))
    )
    lower_bounds = np.concatenate(
        (np.sqrt(pressure[:-1] * pressure[1:]), [100.0])
    )
    for upper, lower, value in zip(upper_bounds, lower_bounds, scalar):
        axis.axhspan(
            upper,
            lower,
            color=color_map(norm(value)),
            alpha=0.76,
            linewidth=0,
        )

    normalized = np.clip((scalar - value_min) / (value_max - value_min), 0, 1)
    axis.plot(
        normalized,
        pressure,
        color="white",
        linewidth=3.2,
        alpha=0.42,
    )
    axis.plot(
        normalized,
        pressure,
        color="#40565e",
        linewidth=0.75,
        alpha=0.70,
    )


def add_english_header(
    figure: object,
    profile: SoundingProfile,
    *,
    diagram_label: str,
    station_name: str | None,
    font_properties: FontProperties | None,
    diagnostics: SoundingDiagnostics,
) -> None:
    font_options = font_kwargs(font_properties)
    station_label = station_name or f"WMO {profile.station_id}"
    valid_label = profile.valid_at.strftime("%Y-%m-%d %H UTC")
    figure.suptitle(
        f"{station_label} | {diagram_label}",
        x=0.065,
        y=0.984,
        ha="left",
        color="#253744",
        fontsize=20,
        fontweight=700,
        **font_options,
    )
    figure.text(
        0.065,
        0.948,
        (
            f"WMO {profile.station_id}  |  {valid_label}  |  "
            f"{profile.level_count} levels  |  {profile.source}"
        ),
        color="#7a7069",
        fontsize=10.5,
        **font_options,
    )
    figure.text(
        0.935,
        0.982,
        "@CloudyLake",
        ha="right",
        va="top",
        color="#126e68",
        fontsize=11,
        fontweight=700,
        **font_options,
    )
    figure.text(
        0.935,
        0.948,
        (
            f"SBCAPE {diagnostics.cape_j_kg or 0:.0f} J/kg  |  "
            f"SBCIN {diagnostics.cin_j_kg or 0:.0f} J/kg  |  "
            f"LCL {diagnostics.lcl_pressure_hpa or 0:.0f} hPa"
        ),
        ha="right",
        color="#7a7069",
        fontsize=9.5,
        **font_options,
    )
    figure.text(
        0.065,
        0.025,
        "CloudyLake's Observatory V2.1.1 | Automatically generated quicklook",
        color="#8a817b",
        fontsize=9,
        **font_options,
    )


def add_figure_legend(
    figure: object,
    *,
    font_properties: FontProperties | None,
) -> None:
    legend_font = (
        font_properties.copy()
        if font_properties is not None
        else FontProperties()
    )
    legend_font.set_size(9)
    handles = [
        Line2D([], [], color="#df2727", linewidth=2.2, label="Temperature"),
        Line2D([], [], color="#287c70", linewidth=2.2, label="Dew Point"),
        Line2D(
            [],
            [],
            color="#8463a6",
            linewidth=1.5,
            linestyle="--",
            label="Virtual Temperature",
        ),
        Line2D(
            [],
            [],
            color="#d39143",
            linewidth=1.6,
            linestyle=":",
            label="Surface Parcel",
        ),
        Patch(color="#eaa66c", alpha=0.34, label="CAPE"),
        Patch(color="#77a7c9", alpha=0.32, label="CIN"),
    ]
    figure.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.48, 0.942),
        ncol=6,
        frameon=False,
        handlelength=2.0,
        columnspacing=1.2,
        prop=legend_font,
    )


def save_product(
    figure: object,
    profile: SoundingProfile,
    *,
    product_root: Path,
    diagram_type: Literal["skewt", "stuve"],
    station_name: str | None,
) -> SoundingProduct:
    generated_at = datetime.now(timezone.utc)
    product_directory = (
        Path(product_root)
        / "soundings"
        / f"{profile.valid_at:%Y}"
        / f"{profile.valid_at:%m}"
        / f"{profile.valid_at:%d}"
    )
    product_directory.mkdir(parents=True, exist_ok=True)
    stem = f"{profile.station_id}_{profile.valid_at:%H}_{diagram_type}"
    image_path = product_directory / f"{stem}.png"
    metadata_path = product_directory / f"{stem}.json"
    temporary_path = product_directory / f"{stem}.tmp.png"

    figure.savefig(
        temporary_path,
        dpi=165,
        facecolor="white",
        bbox_inches="tight",
        metadata={
            "Title": (
                f"{station_name or profile.station_id} "
                f"{profile.valid_at:%Y-%m-%d %H UTC} {diagram_type}"
            ),
            "Source": profile.source,
            "Software": f"CloudyLake's Observatory {RENDERER_VERSION}",
        },
    )
    plt.close(figure)
    os.replace(temporary_path, image_path)

    relative_path = image_path.relative_to(product_root).as_posix()
    product = SoundingProduct(
        station_id=profile.station_id,
        station_name=station_name,
        valid_at=profile.valid_at,
        source=profile.source,
        generated_at=generated_at,
        renderer_version=RENDERER_VERSION,
        diagram_type=diagram_type,
        level_count=profile.level_count,
        image_path=relative_path,
        image_url=f"/products/{relative_path}",
    )
    metadata_path.write_text(
        json.dumps(
            product.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return product


def load_font(font_path: Path | None) -> FontProperties | None:
    if font_path is None or not Path(font_path).exists():
        return None
    fontManager.addfont(str(font_path))
    return FontProperties(fname=str(font_path))


def font_kwargs(
    font_properties: FontProperties | None,
) -> dict[str, FontProperties]:
    if font_properties is None:
        return {}
    return {"fontproperties": font_properties}
