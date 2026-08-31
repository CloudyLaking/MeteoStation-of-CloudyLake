from __future__ import annotations

import math

import numpy as np
from metpy.calc import (
    bunkers_storm_motion,
    cape_cin,
    critical_angle,
    downdraft_cape,
    el,
    equivalent_potential_temperature,
    lcl,
    lfc,
    mixed_layer_cape_cin,
    most_unstable_cape_cin,
    parcel_profile,
    precipitable_water,
    relative_humidity_from_dewpoint,
    significant_tornado,
    storm_relative_helicity,
    sweat_index,
    virtual_temperature_from_dewpoint,
    wet_bulb_temperature,
)
from metpy.units import units

from .models import (
    SoundingDiagnostics,
    SoundingCorrectionInput,
    SoundingLevel,
    SoundingProfile,
    SoundingStructure,
    ThermodynamicDiagnosticLevel,
)


def calculate_sounding_diagnostics(
    profile: SoundingProfile,
    *,
    minimum_pressure_hpa: float = 100,
) -> SoundingDiagnostics:
    """Calculate surface-based thermodynamic diagnostics for a profile."""
    usable_levels = []
    seen_pressures: set[float] = set()

    for level in profile.levels:
        if (
            level.pressure_hpa < minimum_pressure_hpa
            or level.temperature_c is None
            or level.dewpoint_c is None
        ):
            continue
        pressure_key = round(level.pressure_hpa, 3)
        if pressure_key in seen_pressures:
            continue
        seen_pressures.add(pressure_key)
        usable_levels.append(level)

    usable_levels.sort(key=lambda level: level.pressure_hpa, reverse=True)
    if len(usable_levels) < 3:
        raise ValueError(
            "At least three temperature/dew-point levels are required "
            "for thermodynamic diagnostics"
        )

    pressure = np.asarray(
        [level.pressure_hpa for level in usable_levels]
    ) * units.hPa
    temperature = np.asarray(
        [level.temperature_c for level in usable_levels]
    ) * units.degC
    dewpoint = np.asarray(
        [level.dewpoint_c for level in usable_levels]
    ) * units.degC

    virtual_temperature = virtual_temperature_from_dewpoint(
        pressure,
        temperature,
        dewpoint,
    ).to(units.degC)
    wet_bulb = wet_bulb_temperature(
        pressure,
        temperature,
        dewpoint,
    ).to(units.degC)
    equivalent_potential = equivalent_potential_temperature(
        pressure,
        temperature,
        dewpoint,
    ).to(units.kelvin)
    parcel_temperature = parcel_profile(
        pressure,
        temperature[0],
        dewpoint[0],
    ).to(units.degC)
    lcl_pressure, lcl_temperature = lcl(
        pressure[0],
        temperature[0],
        dewpoint[0],
    )
    cape, cin = cape_cin(
        pressure,
        temperature,
        dewpoint,
        parcel_temperature,
    )
    lfc_pressure, _ = lfc(
        pressure,
        temperature,
        dewpoint,
        parcel_temperature_profile=parcel_temperature,
        which="bottom",
    )
    equilibrium_pressure, _ = el(
        pressure,
        temperature,
        dewpoint,
        parcel_temperature_profile=parcel_temperature,
        which="top",
    )
    precipitable_water_value = precipitable_water(
        pressure,
        dewpoint,
    )
    mixed_layer_cape, mixed_layer_cin = safe_quantity_pair(
        mixed_layer_cape_cin,
        pressure,
        temperature,
        dewpoint,
        depth=100 * units.hPa,
    )
    most_unstable_cape, most_unstable_cin = safe_quantity_pair(
        most_unstable_cape_cin,
        pressure,
        temperature,
        dewpoint,
        depth=300 * units.hPa,
    )
    dcape_value = safe_dcape(pressure, temperature, dewpoint)

    pressure_values = pressure.to("hPa").magnitude
    temperature_values = temperature.to("degC").magnitude
    dewpoint_values = dewpoint.to("degC").magnitude
    parcel_values = parcel_temperature.to("degC").magnitude
    temperature_850 = log_pressure_interpolate(
        pressure_values,
        temperature_values,
        850,
    )
    temperature_700 = log_pressure_interpolate(
        pressure_values,
        temperature_values,
        700,
    )
    temperature_500 = log_pressure_interpolate(
        pressure_values,
        temperature_values,
        500,
    )
    dewpoint_850 = log_pressure_interpolate(
        pressure_values,
        dewpoint_values,
        850,
    )
    dewpoint_700 = log_pressure_interpolate(
        pressure_values,
        dewpoint_values,
        700,
    )
    parcel_500 = log_pressure_interpolate(
        pressure_values,
        parcel_values,
        500,
    )
    lifted_index = difference(temperature_500, parcel_500)
    k_index = sum_if_complete(
        difference(temperature_850, temperature_500),
        dewpoint_850,
        difference(dewpoint_700, temperature_700),
    )
    total_totals = sum_if_complete(
        temperature_850,
        dewpoint_850,
        None if temperature_500 is None else -2 * temperature_500,
    )
    freezing_pressure, freezing_height = freezing_level(usable_levels)
    lcl_height_agl = pressure_level_height_agl(
        usable_levels,
        finite_magnitude(lcl_pressure, "hPa"),
    )
    lfc_height_agl = pressure_level_height_agl(
        usable_levels,
        finite_magnitude(lfc_pressure, "hPa"),
    )
    equilibrium_height_agl = pressure_level_height_agl(
        usable_levels,
        finite_magnitude(equilibrium_pressure, "hPa"),
    )
    wind_diagnostics = calculate_wind_diagnostics(usable_levels)
    sweat_value = calculate_sweat_index(usable_levels)
    fixed_stp = calculate_fixed_layer_stp(
        cape=finite_magnitude(cape, "J/kg"),
        lcl_height_agl_m=lcl_height_agl,
        srh_0_1km=wind_diagnostics["srh_0_1km"],
        shear_0_6km=wind_diagnostics["shear_0_6km"],
    )
    lapse_rate = lapse_rate_700_500(usable_levels)
    structures = identify_vertical_structures(usable_levels)

    levels = [
        ThermodynamicDiagnosticLevel(
            pressure_hpa=float(level.pressure_hpa),
            virtual_temperature_c=float(virtual.to(units.degC).magnitude),
            wet_bulb_temperature_c=float(wet_bulb_value.to(units.degC).magnitude),
            parcel_temperature_c=float(parcel.to(units.degC).magnitude),
            equivalent_potential_temperature_k=float(
                theta_e_value.to(units.kelvin).magnitude
            ),
        )
        for level, virtual, wet_bulb_value, parcel, theta_e_value in zip(
            usable_levels,
            virtual_temperature,
            wet_bulb,
            parcel_temperature,
            equivalent_potential,
        )
    ]
    return SoundingDiagnostics(
        station_id=profile.station_id,
        valid_at=profile.valid_at,
        lcl_pressure_hpa=finite_magnitude(lcl_pressure, "hPa"),
        lcl_temperature_c=finite_magnitude(lcl_temperature, "degC"),
        lfc_pressure_hpa=finite_magnitude(lfc_pressure, "hPa"),
        equilibrium_level_pressure_hpa=finite_magnitude(
            equilibrium_pressure,
            "hPa",
        ),
        cape_j_kg=finite_magnitude(cape, "J/kg"),
        cin_j_kg=finite_magnitude(cin, "J/kg"),
        mixed_layer_cape_j_kg=finite_magnitude(
            mixed_layer_cape,
            "J/kg",
        ),
        mixed_layer_cin_j_kg=finite_magnitude(
            mixed_layer_cin,
            "J/kg",
        ),
        most_unstable_cape_j_kg=finite_magnitude(
            most_unstable_cape,
            "J/kg",
        ),
        most_unstable_cin_j_kg=finite_magnitude(
            most_unstable_cin,
            "J/kg",
        ),
        dcape_j_kg=finite_magnitude(dcape_value, "J/kg"),
        precipitable_water_mm=finite_magnitude(
            precipitable_water_value,
            "mm",
        ),
        lifted_index_c=lifted_index,
        k_index_c=k_index,
        total_totals_index=total_totals,
        sweat_index=sweat_value,
        lcl_height_agl_m=lcl_height_agl,
        lfc_height_agl_m=lfc_height_agl,
        equilibrium_level_height_agl_m=equilibrium_height_agl,
        freezing_level_pressure_hpa=freezing_pressure,
        freezing_level_height_m=freezing_height,
        bulk_shear_0_1km_ms=wind_diagnostics["shear_0_1km"],
        bulk_shear_0_3km_ms=wind_diagnostics["shear_0_3km"],
        bulk_shear_0_6km_ms=wind_diagnostics["shear_0_6km"],
        storm_relative_helicity_0_1km_m2_s2=(
            wind_diagnostics["srh_0_1km"]
        ),
        storm_relative_helicity_0_3km_m2_s2=(
            wind_diagnostics["srh_0_3km"]
        ),
        bunkers_right_motion_u_ms=wind_diagnostics["right_u"],
        bunkers_right_motion_v_ms=wind_diagnostics["right_v"],
        bunkers_left_motion_u_ms=wind_diagnostics["left_u"],
        bunkers_left_motion_v_ms=wind_diagnostics["left_v"],
        mean_wind_0_6km_u_ms=wind_diagnostics["mean_u"],
        mean_wind_0_6km_v_ms=wind_diagnostics["mean_v"],
        critical_angle_deg=wind_diagnostics["critical_angle"],
        significant_tornado_fixed=fixed_stp,
        lapse_rate_700_500_c_km=lapse_rate,
        structures=structures,
        levels=levels,
    )


def identify_vertical_structures(levels: list[SoundingLevel]) -> list[SoundingStructure]:
    """Identify readable vertical features from observed levels only.

    The thresholds are deliberately conservative.  Results are diagnostic
    hints with an explicit confidence, rather than categorical forecasts.
    """
    ordered = sorted(
        [level for level in levels if level.temperature_c is not None],
        key=lambda level: level.pressure_hpa,
        reverse=True,
    )
    if len(ordered) < 3:
        return []
    surface_height = next(
        (float(level.geopotential_height_m) for level in ordered if level.geopotential_height_m is not None),
        0.0,
    )

    def height(level: SoundingLevel) -> float:
        if level.geopotential_height_m is not None:
            return float(level.geopotential_height_m) - surface_height
        return 8434.5 * math.log(ordered[0].pressure_hpa / level.pressure_hpa)

    def humidity(level: SoundingLevel) -> float | None:
        if level.relative_humidity_pct is not None:
            return float(level.relative_humidity_pct)
        if level.dewpoint_c is None or level.temperature_c is None:
            return None
        saturation = math.exp(17.625 * level.temperature_c / (243.04 + level.temperature_c))
        actual = math.exp(17.625 * level.dewpoint_c / (243.04 + level.dewpoint_c))
        return max(0.0, min(100.0, 100.0 * actual / saturation))

    found: list[SoundingStructure] = []

    # Merge adjacent layers that share the same humidity regime.
    for kind, label, predicate in (
        ("moist_layer", "湿层", lambda value: value >= 80),
        ("dry_layer", "干层", lambda value: value <= 30),
    ):
        start: int | None = None
        for index, level in enumerate(ordered + [ordered[-1]]):
            value = humidity(level) if index < len(ordered) else None
            active = value is not None and predicate(value)
            if active and start is None:
                start = index
            if start is not None and (not active or index == len(ordered) - 1):
                end = index if active else index - 1
                bottom, top = ordered[start], ordered[end]
                depth = height(top) - height(bottom)
                if end > start and depth >= 300:
                    values = [humidity(item) for item in ordered[start:end + 1]]
                    mean = sum(value for value in values if value is not None) / len([value for value in values if value is not None])
                    found.append(SoundingStructure(
                        kind=kind, label=label,
                        bottom_pressure_hpa=bottom.pressure_hpa, top_pressure_hpa=top.pressure_hpa,
                        bottom_height_agl_m=round(height(bottom)), top_height_agl_m=round(height(top)),
                        strength=round(mean, 1), confidence="高" if len(values) >= 3 else "中",
                        summary=f"{round(height(bottom))}—{round(height(top))} 米，相对湿度均值约 {mean:.0f}%",
                    ))
                start = None

    # Temperature increase with height across at least one reported layer.
    for lower, upper in zip(ordered, ordered[1:]):
        depth = height(upper) - height(lower)
        warming = float(upper.temperature_c) - float(lower.temperature_c)
        if 80 <= depth <= 2500 and warming >= 1.5:
            found.append(SoundingStructure(
                kind="inversion", label="逆温层",
                bottom_pressure_hpa=lower.pressure_hpa, top_pressure_hpa=upper.pressure_hpa,
                bottom_height_agl_m=round(height(lower)), top_height_agl_m=round(height(upper)),
                strength=round(warming, 1), confidence="高" if warming >= 3 else "中",
                summary=f"{round(height(lower))}—{round(height(upper))} 米，升温 {warming:.1f} ℃",
            ))

    # Local wind maximum below 3 km with a meaningful decrease above it.
    wind_levels = [(index, level) for index, level in enumerate(ordered) if level.wind_speed_ms is not None and height(level) <= 3000]
    if len(wind_levels) >= 3:
        peak_index, peak = max(wind_levels, key=lambda item: float(item[1].wind_speed_ms))
        above = [level for level in ordered[peak_index + 1:] if level.wind_speed_ms is not None and height(level) <= 4500]
        decrease = float(peak.wind_speed_ms) - min((float(level.wind_speed_ms) for level in above), default=float(peak.wind_speed_ms))
        if float(peak.wind_speed_ms) >= 12 and decrease >= 4:
            found.append(SoundingStructure(
                kind="low_level_jet", label="低空急流",
                bottom_pressure_hpa=peak.pressure_hpa, top_pressure_hpa=peak.pressure_hpa,
                bottom_height_agl_m=round(height(peak)), top_height_agl_m=round(height(peak)),
                strength=round(float(peak.wind_speed_ms), 1), confidence="高" if decrease >= 7 else "中",
                summary=f"约 {round(height(peak))} 米风速峰值 {float(peak.wind_speed_ms):.1f} 米/秒",
            ))

    # First level above 7 km followed by a 2 km mean lapse rate <= 2 °C/km.
    for index, lower in enumerate(ordered[:-1]):
        lower_height = height(lower)
        if lower_height < 7000:
            continue
        candidates = [upper for upper in ordered[index + 1:] if height(upper) - lower_height >= 1800]
        if not candidates:
            continue
        upper = candidates[0]
        lapse = (float(lower.temperature_c) - float(upper.temperature_c)) / ((height(upper) - lower_height) / 1000)
        if lapse <= 2:
            found.append(SoundingStructure(
                kind="tropopause", label="对流层顶候选",
                bottom_pressure_hpa=lower.pressure_hpa, top_pressure_hpa=upper.pressure_hpa,
                bottom_height_agl_m=round(lower_height), top_height_agl_m=round(height(upper)),
                strength=round(lapse, 1), confidence="中" if len(ordered[index:]) >= 3 else "低",
                summary=f"约 {round(lower_height)} 米起，向上约 2 千米平均递减率 {lapse:.1f} ℃/千米",
            ))
            break
    return sorted(found, key=lambda item: item.bottom_height_agl_m or 0)


def safe_quantity_pair(
    function: object,
    *args: object,
    **kwargs: object,
) -> tuple[object | None, object | None]:
    try:
        left, right = function(*args, **kwargs)
    except (IndexError, TypeError, ValueError):
        return None, None
    return left, right


def safe_dcape(
    pressure: object,
    temperature: object,
    dewpoint: object,
) -> object | None:
    try:
        dcape, _, _ = downdraft_cape(pressure, temperature, dewpoint)
    except (IndexError, TypeError, ValueError):
        return None
    return dcape


def pressure_level_height_agl(
    levels: list[SoundingLevel],
    target_pressure_hpa: float | None,
) -> float | None:
    if target_pressure_hpa is None:
        return None
    height_levels = [
        level
        for level in levels
        if level.geopotential_height_m is not None
    ]
    if len(height_levels) < 2:
        return None
    pressures = np.asarray(
        [level.pressure_hpa for level in height_levels],
        dtype=float,
    )
    heights = np.asarray(
        [level.geopotential_height_m for level in height_levels],
        dtype=float,
    )
    target_height = log_pressure_interpolate(
        pressures,
        heights,
        target_pressure_hpa,
    )
    if target_height is None:
        return None
    surface_height = float(heights[0])
    return max(0.0, target_height - surface_height)


def calculate_wind_diagnostics(
    levels: list[SoundingLevel],
) -> dict[str, float | None]:
    result: dict[str, float | None] = {
        "shear_0_1km": None,
        "shear_0_3km": None,
        "shear_0_6km": None,
        "srh_0_1km": None,
        "srh_0_3km": None,
        "right_u": None,
        "right_v": None,
        "left_u": None,
        "left_v": None,
        "mean_u": None,
        "mean_v": None,
        "critical_angle": None,
    }
    wind_levels = [
        level
        for level in levels
        if level.geopotential_height_m is not None
        and level.wind_direction_deg is not None
        and level.wind_speed_ms is not None
    ]
    wind_levels.sort(key=lambda level: level.geopotential_height_m or 0)
    if len(wind_levels) < 3:
        return result

    height_values = np.asarray(
        [level.geopotential_height_m for level in wind_levels],
        dtype=float,
    )
    base_height = float(height_values[0])
    height_agl = height_values - base_height
    direction_radians = np.radians(
        [level.wind_direction_deg for level in wind_levels]
    )
    speed_values = np.asarray(
        [level.wind_speed_ms for level in wind_levels],
        dtype=float,
    )
    u_values = -speed_values * np.sin(direction_radians)
    v_values = -speed_values * np.cos(direction_radians)

    for depth_km in (1, 3, 6):
        key = f"shear_0_{depth_km}km"
        if height_agl[-1] < depth_km * 1000:
            continue
        target_u = float(
            np.interp(depth_km * 1000, height_agl, u_values)
        )
        target_v = float(
            np.interp(depth_km * 1000, height_agl, v_values)
        )
        result[key] = math.hypot(
            target_u - float(u_values[0]),
            target_v - float(v_values[0]),
        )

    if height_agl[-1] < 6000:
        return result

    pressure = (
        np.asarray([level.pressure_hpa for level in wind_levels])
        * units.hPa
    )
    height = height_values * units.m
    u_wind = u_values * units("m/s")
    v_wind = v_values * units("m/s")
    try:
        right_motion, left_motion, mean_wind = bunkers_storm_motion(
            pressure,
            u_wind,
            v_wind,
            height,
        )
        result["right_u"] = finite_magnitude(right_motion[0], "m/s")
        result["right_v"] = finite_magnitude(right_motion[1], "m/s")
        result["left_u"] = finite_magnitude(left_motion[0], "m/s")
        result["left_v"] = finite_magnitude(left_motion[1], "m/s")
        result["mean_u"] = finite_magnitude(mean_wind[0], "m/s")
        result["mean_v"] = finite_magnitude(mean_wind[1], "m/s")

        for depth_km in (1, 3):
            _, _, total_helicity = storm_relative_helicity(
                height,
                u_wind,
                v_wind,
                depth_km * units.km,
                bottom=base_height * units.m,
                storm_u=right_motion[0],
                storm_v=right_motion[1],
            )
            result[f"srh_0_{depth_km}km"] = finite_magnitude(
                total_helicity,
                "m^2/s^2",
            )
        angle = critical_angle(
            pressure,
            u_wind,
            v_wind,
            height,
            right_motion[0],
            right_motion[1],
        )
        result["critical_angle"] = finite_magnitude(angle, "degree")
    except (IndexError, TypeError, ValueError, ZeroDivisionError):
        return result
    return result


def calculate_sweat_index(
    levels: list[SoundingLevel],
) -> float | None:
    complete = [
        level
        for level in levels
        if level.temperature_c is not None
        and level.dewpoint_c is not None
        and level.wind_direction_deg is not None
        and level.wind_speed_ms is not None
    ]
    if len(complete) < 3:
        return None
    pressures = np.asarray(
        [level.pressure_hpa for level in complete],
        dtype=float,
    )
    temperatures = np.asarray(
        [level.temperature_c for level in complete],
        dtype=float,
    )
    dewpoints = np.asarray(
        [level.dewpoint_c for level in complete],
        dtype=float,
    )
    directions = np.radians(
        [level.wind_direction_deg for level in complete]
    )
    speeds = np.asarray(
        [level.wind_speed_ms for level in complete],
        dtype=float,
    )
    u_values = -speeds * np.sin(directions)
    v_values = -speeds * np.cos(directions)
    target_temperatures: list[float] = []
    target_dewpoints: list[float] = []
    target_speeds: list[float] = []
    target_directions: list[float] = []
    for target_pressure in (850, 500):
        temperature = log_pressure_interpolate(
            pressures,
            temperatures,
            target_pressure,
        )
        dewpoint = log_pressure_interpolate(
            pressures,
            dewpoints,
            target_pressure,
        )
        u_wind = log_pressure_interpolate(
            pressures,
            u_values,
            target_pressure,
        )
        v_wind = log_pressure_interpolate(
            pressures,
            v_values,
            target_pressure,
        )
        if None in (temperature, dewpoint, u_wind, v_wind):
            return None
        target_temperatures.append(float(temperature))
        target_dewpoints.append(float(dewpoint))
        target_speeds.append(math.hypot(float(u_wind), float(v_wind)))
        target_directions.append(
            math.degrees(math.atan2(-float(u_wind), -float(v_wind)))
            % 360
        )
    try:
        value = sweat_index(
            np.asarray([850, 500]) * units.hPa,
            np.asarray(target_temperatures) * units.degC,
            np.asarray(target_dewpoints) * units.degC,
            np.asarray(target_speeds) * units("m/s"),
            np.asarray(target_directions) * units.degree,
        )
    except (IndexError, TypeError, ValueError):
        return None
    return finite_magnitude(value, "dimensionless")


def calculate_fixed_layer_stp(
    *,
    cape: float | None,
    lcl_height_agl_m: float | None,
    srh_0_1km: float | None,
    shear_0_6km: float | None,
) -> float | None:
    if None in (cape, lcl_height_agl_m, srh_0_1km, shear_0_6km):
        return None
    try:
        value = significant_tornado(
            cape * units("J/kg"),
            lcl_height_agl_m * units.m,
            srh_0_1km * units("m^2/s^2"),
            shear_0_6km * units("m/s"),
        )
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return finite_magnitude(value, "dimensionless")


def apply_surface_correction(
    profile: SoundingProfile,
    correction: SoundingCorrectionInput,
) -> SoundingProfile:
    """Insert a corrected surface level without changing archived source data."""
    if correction.dewpoint_c > correction.temperature_c + 0.5:
        raise ValueError("Dew point cannot exceed temperature by more than 0.5 °C")

    original_surface = max(
        profile.levels,
        key=lambda level: level.pressure_hpa,
    )
    relative_humidity = relative_humidity_from_dewpoint(
        correction.temperature_c * units.degC,
        correction.dewpoint_c * units.degC,
    ).to("dimensionless")
    corrected_surface = SoundingLevel(
        observed_at=profile.valid_at,
        longitude=profile.station_longitude,
        latitude=profile.station_latitude,
        pressure_hpa=correction.pressure_hpa,
        geopotential_height_m=original_surface.geopotential_height_m,
        temperature_c=correction.temperature_c,
        dewpoint_c=correction.dewpoint_c,
        relative_humidity_pct=float(relative_humidity.magnitude) * 100,
        wind_direction_deg=original_surface.wind_direction_deg,
        wind_speed_ms=original_surface.wind_speed_ms,
    )
    levels = [corrected_surface]
    levels.extend(
        level
        for level in profile.levels
        if level.pressure_hpa < correction.pressure_hpa - 0.05
    )
    levels.sort(key=lambda level: level.pressure_hpa, reverse=True)
    return profile.model_copy(
        update={
            "source": f"{profile.source} + {correction.source_label} correction",
            "cache_status": "corrected",
            "level_count": len(levels),
            "surface_pressure_hpa": correction.pressure_hpa,
            "top_pressure_hpa": min(level.pressure_hpa for level in levels),
            "levels": levels,
        }
    )


def finite_magnitude(quantity: object, unit: str) -> float | None:
    try:
        magnitude = np.asarray(quantity.to(unit).magnitude)
    except (AttributeError, TypeError, ValueError):
        return None
    if magnitude.size != 1:
        return None
    value = float(magnitude.reshape(-1)[0])
    return value if math.isfinite(value) else None


def log_pressure_interpolate(
    pressures: np.ndarray,
    values: np.ndarray,
    target_pressure: float,
) -> float | None:
    if target_pressure > np.max(pressures) or target_pressure < np.min(pressures):
        return None
    value = float(
        np.interp(
            math.log(target_pressure),
            np.log(pressures[::-1]),
            values[::-1],
        )
    )
    return value if math.isfinite(value) else None


def difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def sum_if_complete(*values: float | None) -> float | None:
    if any(value is None for value in values):
        return None
    return float(sum(value for value in values if value is not None))


def freezing_level(
    levels: list[SoundingLevel],
) -> tuple[float | None, float | None]:
    for lower, upper in zip(levels, levels[1:]):
        if lower.temperature_c is None or upper.temperature_c is None:
            continue
        if lower.temperature_c >= 0 >= upper.temperature_c:
            span = lower.temperature_c - upper.temperature_c
            fraction = 0 if span == 0 else lower.temperature_c / span
            log_pressure = math.log(lower.pressure_hpa) + fraction * (
                math.log(upper.pressure_hpa) - math.log(lower.pressure_hpa)
            )
            height = None
            if (
                lower.geopotential_height_m is not None
                and upper.geopotential_height_m is not None
            ):
                height = lower.geopotential_height_m + fraction * (
                    upper.geopotential_height_m
                    - lower.geopotential_height_m
                )
            return math.exp(log_pressure), height
    return None, None


def bulk_shear_0_6km(levels: list[SoundingLevel]) -> float | None:
    wind_levels = [
        level
        for level in levels
        if level.geopotential_height_m is not None
        and level.wind_direction_deg is not None
        and level.wind_speed_ms is not None
    ]
    if len(wind_levels) < 2:
        return None
    wind_levels.sort(key=lambda level: level.geopotential_height_m or 0)
    base_height = wind_levels[0].geopotential_height_m
    if base_height is None:
        return None
    target_height = base_height + 6000
    if (wind_levels[-1].geopotential_height_m or 0) < target_height:
        return None
    heights = np.asarray(
        [level.geopotential_height_m for level in wind_levels],
        dtype=float,
    )
    directions = np.radians(
        [level.wind_direction_deg for level in wind_levels]
    )
    speeds = np.asarray([level.wind_speed_ms for level in wind_levels])
    u = -speeds * np.sin(directions)
    v = -speeds * np.cos(directions)
    target_u = float(np.interp(target_height, heights, u))
    target_v = float(np.interp(target_height, heights, v))
    return math.hypot(target_u - float(u[0]), target_v - float(v[0]))


def lapse_rate_700_500(levels: list[SoundingLevel]) -> float | None:
    height_levels = [
        level
        for level in levels
        if level.temperature_c is not None
        and level.geopotential_height_m is not None
    ]
    if len(height_levels) < 2:
        return None
    height_levels.sort(key=lambda level: level.pressure_hpa, reverse=True)
    pressures = np.asarray([level.pressure_hpa for level in height_levels])
    temperatures = np.asarray([level.temperature_c for level in height_levels])
    heights = np.asarray([level.geopotential_height_m for level in height_levels])
    temperature_700 = log_pressure_interpolate(pressures, temperatures, 700)
    temperature_500 = log_pressure_interpolate(pressures, temperatures, 500)
    height_700 = log_pressure_interpolate(pressures, heights, 700)
    height_500 = log_pressure_interpolate(pressures, heights, 500)
    if None in (temperature_700, temperature_500, height_700, height_500):
        return None
    depth_km = (height_500 - height_700) / 1000
    if depth_km <= 0:
        return None
    return (temperature_700 - temperature_500) / depth_km
