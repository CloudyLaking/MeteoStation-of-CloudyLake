"""Decode indexed WIS2 TEMP BUFR parts into one normalized sounding profile."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Literal

from eccodes import codes_bufr_new_from_file, codes_get_array, codes_release, codes_set

from .models import SoundingLevel, SoundingProfile


class Wis2SoundingNotFound(RuntimeError):
    pass


def _array(handle, key: str) -> list[float]:
    try:
        return [float(value) for value in codes_get_array(handle, key)]
    except Exception:
        return []


def _valid(value: float | None, minimum: float, maximum: float) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return value if minimum <= value <= maximum else None


class Wis2SoundingArchive:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def load_profile(
        self,
        station_id: str,
        sounding_date: date,
        cycle: Literal["00", "12"],
    ) -> SoundingProfile:
        valid_at = datetime.combine(
            sounding_date,
            time(hour=int(cycle)),
            tzinfo=timezone.utc,
        )
        directory = self.root / f"{valid_at:%Y}" / f"{valid_at:%m}" / f"{valid_at:%d}"
        index_path = directory / "index.json"
        if not index_path.exists():
            raise Wis2SoundingNotFound("WIS2 站次索引中没有该探空")

        index = json.loads(index_path.read_text(encoding="utf-8"))
        entries = index.get("items", {}).get(
            f"{station_id}|{valid_at.isoformat()}",
            [],
        )
        if not entries:
            raise Wis2SoundingNotFound("WIS2 尚未收到该站次")

        levels_by_pressure: dict[float, SoundingLevel] = {}
        sources: list[str] = []
        fetched: list[datetime] = []
        for entry in entries:
            data_path = directory / str(entry.get("data_file", ""))
            if not data_path.is_file():
                continue
            sources.append(str(entry.get("source_url", "")))
            if entry.get("downloaded_at"):
                try:
                    fetched.append(datetime.fromisoformat(str(entry["downloaded_at"])))
                except ValueError:
                    pass

            with data_path.open("rb") as handle_file:
                while handle := codes_bufr_new_from_file(handle_file):
                    try:
                        codes_set(handle, "unpack", 1)
                        pressure = _array(handle, "pressure")
                        height = _array(handle, "nonCoordinateGeopotentialHeight")
                        temperature = _array(handle, "airTemperature")
                        dewpoint = _array(handle, "dewpointTemperature")
                        wind_direction = _array(handle, "windDirection")
                        wind_speed = _array(handle, "windSpeed")
                        latitude = _array(handle, "latitude")
                        longitude = _array(handle, "longitude")
                        lat = _valid(latitude[0] if latitude else None, -90, 90)
                        lon = _valid(longitude[0] if longitude else None, -180, 180)
                        if lat is None or lon is None:
                            continue

                        for index_value, pressure_pa in enumerate(pressure):
                            pressure_hpa = _valid(pressure_pa / 100, 0.1, 1100)
                            if pressure_hpa is None:
                                continue

                            def value(array: list[float]) -> float | None:
                                return array[index_value] if index_value < len(array) else None

                            air_kelvin = _valid(value(temperature), 100, 350)
                            dewpoint_kelvin = _valid(value(dewpoint), 100, 350)
                            candidate = SoundingLevel(
                                observed_at=valid_at,
                                latitude=lat,
                                longitude=lon,
                                pressure_hpa=pressure_hpa,
                                geopotential_height_m=_valid(value(height), -500, 60000),
                                temperature_c=air_kelvin - 273.15 if air_kelvin is not None else None,
                                dewpoint_c=dewpoint_kelvin - 273.15 if dewpoint_kelvin is not None else None,
                                wind_direction_deg=_valid(value(wind_direction), 0, 360),
                                wind_speed_ms=_valid(value(wind_speed), 0, 200),
                            )
                            pressure_key = round(pressure_hpa, 2)
                            previous = levels_by_pressure.get(pressure_key)
                            candidate_values = (
                                candidate.temperature_c,
                                candidate.dewpoint_c,
                                candidate.geopotential_height_m,
                                candidate.wind_speed_ms,
                            )
                            score = sum(item is not None for item in candidate_values)
                            if previous is None:
                                previous_score = -1
                            else:
                                previous_values = (
                                    previous.temperature_c,
                                    previous.dewpoint_c,
                                    previous.geopotential_height_m,
                                    previous.wind_speed_ms,
                                )
                                previous_score = sum(item is not None for item in previous_values)
                            if score > previous_score:
                                levels_by_pressure[pressure_key] = candidate
                    finally:
                        codes_release(handle)

        levels = sorted(
            levels_by_pressure.values(),
            key=lambda level: level.pressure_hpa,
            reverse=True,
        )
        if len(levels) < 5:
            raise Wis2SoundingNotFound("WIS2 TEMP 分段尚未组成可用廓线")

        return SoundingProfile(
            station_id=station_id,
            valid_at=valid_at,
            source="WMO WIS 2.0 TEMP",
            source_url=next(
                (url for url in sources if url),
                "https://community.wmo.int/en/activity-areas/wis/wis2-overview",
            ),
            fetched_at=max(fetched, default=datetime.now(timezone.utc)),
            cache_status="hit",
            level_count=len(levels),
            surface_pressure_hpa=levels[0].pressure_hpa,
            top_pressure_hpa=levels[-1].pressure_hpa,
            station_longitude=levels[0].longitude,
            station_latitude=levels[0].latitude,
            levels=levels,
        )

