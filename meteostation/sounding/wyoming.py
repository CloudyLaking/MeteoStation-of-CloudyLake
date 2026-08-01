import csv
import hashlib
import json
from datetime import date, datetime, time, timezone
from io import StringIO
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

import httpx

from .models import SoundingLevel, SoundingProfile


WYOMING_ENDPOINT = "https://weather.uwyo.edu/wsgi/sounding"
EXPECTED_HEADER = {
    "time",
    "longitude",
    "latitude",
    "pressure_hPa",
    "geopotential height_m",
    "temperature_C",
    "dew point temperature_C",
    "relative humidity_%",
    "wind direction_degree",
    "wind speed_m/s",
}


class WyomingSoundingError(RuntimeError):
    """Base exception for Wyoming sounding retrieval and parsing."""


class WyomingSoundingNotFound(WyomingSoundingError):
    """The requested station/time has no usable sounding."""


class WyomingSoundingClient:
    def __init__(
        self,
        cache_root: Path,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.cache_root = Path(cache_root)
        self.timeout_seconds = timeout_seconds

    async def get_profile(
        self,
        station_id: str,
        sounding_date: date,
        cycle: Literal["00", "12"],
        *,
        refresh: bool = False,
        source: str = "UNKNOWN",
    ) -> SoundingProfile:
        station_id = validate_station_id(station_id)
        valid_at = datetime.combine(
            sounding_date,
            time(hour=int(cycle)),
            tzinfo=timezone.utc,
        )
        csv_path, metadata_path = self._cache_paths(station_id, valid_at)

        if csv_path.exists() and metadata_path.exists() and not refresh:
            return self.load_cached_profile(
                station_id=station_id,
                sounding_date=sounding_date,
                cycle=cycle,
            )

        source_url = build_wyoming_url(
            station_id,
            valid_at,
            source=source,
        )
        fetched_at = datetime.now(timezone.utc)

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                headers={
                    "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.1",
                    "User-Agent": (
                        "CloudyLake-Observatory/0.1 "
                        "(https://meteostation.top; sounding research)"
                    ),
                },
            ) as client:
                response = await client.get(source_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise WyomingSoundingError(
                f"Wyoming request failed for {station_id} at {valid_at.isoformat()}"
            ) from exc

        raw_csv = response.text.lstrip("\ufeff")
        profile = parse_wyoming_csv(
            raw_csv=raw_csv,
            station_id=station_id,
            valid_at=valid_at,
            source_url=source_url,
            fetched_at=fetched_at,
            cache_status="miss",
        )

        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(raw_csv, encoding="utf-8", newline="")
        metadata = {
            "source": "University of Wyoming",
            "source_url": source_url,
            "station_id": station_id,
            "valid_at": valid_at.isoformat(),
            "fetched_at": fetched_at.isoformat(),
            "sha256": hashlib.sha256(raw_csv.encode("utf-8")).hexdigest(),
            "level_count": profile.level_count,
        }
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return profile

    def load_cached_profile(
        self,
        station_id: str,
        sounding_date: date,
        cycle: Literal["00", "12"],
    ) -> SoundingProfile:
        station_id = validate_station_id(station_id)
        valid_at = datetime.combine(
            sounding_date,
            time(hour=int(cycle)),
            tzinfo=timezone.utc,
        )
        csv_path, metadata_path = self._cache_paths(station_id, valid_at)
        if not csv_path.exists() or not metadata_path.exists():
            raise WyomingSoundingNotFound(
                f"No archived sounding for {station_id} at {valid_at.isoformat()}"
            )

        raw_csv = csv_path.read_text(encoding="utf-8")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return parse_wyoming_csv(
            raw_csv=raw_csv,
            station_id=station_id,
            valid_at=valid_at,
            source_url=metadata["source_url"],
            fetched_at=parse_utc_datetime(metadata["fetched_at"]),
            cache_status="hit",
        )

    def cached_paths(
        self,
        station_id: str,
        sounding_date: date,
        cycle: Literal["00", "12"],
    ) -> tuple[Path, Path]:
        station_id = validate_station_id(station_id)
        valid_at = datetime.combine(
            sounding_date,
            time(hour=int(cycle)),
            tzinfo=timezone.utc,
        )
        return self._cache_paths(station_id, valid_at)

    def _cache_paths(
        self,
        station_id: str,
        valid_at: datetime,
    ) -> tuple[Path, Path]:
        directory = (
            self.cache_root
            / "wyoming"
            / f"{valid_at:%Y}"
            / f"{valid_at:%m}"
            / f"{valid_at:%d}"
        )
        stem = f"{station_id}_{valid_at:%H}"
        return directory / f"{stem}.csv", directory / f"{stem}.json"


def validate_station_id(station_id: str) -> str:
    normalized = station_id.strip()
    if len(normalized) != 5 or not normalized.isdigit():
        raise ValueError("station_id must be a five-digit WMO station number")
    return normalized


def build_wyoming_url(
    station_id: str,
    valid_at: datetime,
    *,
    source: str = "UNKNOWN",
) -> str:
    normalized_source = source.strip().upper() or "UNKNOWN"
    query = urlencode(
        {
            "datetime": valid_at.strftime("%Y-%m-%d %H:%M:%S"),
            "id": station_id,
            "src": normalized_source,
            "type": "TEXT:CSV",
        }
    )
    return f"{WYOMING_ENDPOINT}?{query}"


def parse_wyoming_csv(
    *,
    raw_csv: str,
    station_id: str,
    valid_at: datetime,
    source_url: str,
    fetched_at: datetime,
    cache_status: Literal["hit", "miss"],
) -> SoundingProfile:
    reader = csv.DictReader(StringIO(raw_csv))
    fieldnames = set(reader.fieldnames or [])
    if not EXPECTED_HEADER.issubset(fieldnames):
        raise WyomingSoundingNotFound(
            f"No usable Wyoming CSV for {station_id} at {valid_at.isoformat()}"
        )

    levels: list[SoundingLevel] = []
    for row in reader:
        pressure = to_float(row.get("pressure_hPa"))
        longitude = to_float(row.get("longitude"))
        latitude = to_float(row.get("latitude"))
        observed_at = to_datetime(row.get("time"))

        if (
            pressure is None
            or longitude is None
            or latitude is None
            or observed_at is None
        ):
            continue

        try:
            levels.append(
                SoundingLevel(
                    observed_at=observed_at,
                    longitude=longitude,
                    latitude=latitude,
                    pressure_hpa=pressure,
                    geopotential_height_m=to_float(
                        row.get("geopotential height_m")
                    ),
                    temperature_c=to_float(row.get("temperature_C")),
                    dewpoint_c=to_float(row.get("dew point temperature_C")),
                    ice_point_c=to_float(row.get("ice point temperature_C")),
                    relative_humidity_pct=to_bounded_float(
                        row.get("relative humidity_%"),
                        minimum=0,
                        maximum=110,
                    ),
                    humidity_wrt_ice_pct=to_bounded_float(
                        row.get("humidity wrt ice_%"),
                        minimum=0,
                        maximum=150,
                    ),
                    mixing_ratio_g_kg=to_bounded_float(
                        row.get("mixing ratio_g/kg"),
                        minimum=0,
                    ),
                    wind_direction_deg=to_bounded_float(
                        row.get("wind direction_degree"),
                        minimum=0,
                        maximum=360,
                    ),
                    wind_speed_ms=to_bounded_float(
                        row.get("wind speed_m/s"),
                        minimum=0,
                    ),
                )
            )
        except ValueError:
            continue

    if not levels:
        raise WyomingSoundingNotFound(
            f"Wyoming CSV contained no valid levels for {station_id}"
        )

    levels.sort(key=lambda level: level.pressure_hpa, reverse=True)
    return SoundingProfile(
        station_id=station_id,
        valid_at=valid_at,
        source="University of Wyoming",
        source_url=source_url,
        fetched_at=fetched_at,
        cache_status=cache_status,
        level_count=len(levels),
        surface_pressure_hpa=levels[0].pressure_hpa,
        top_pressure_hpa=levels[-1].pressure_hpa,
        station_longitude=levels[0].longitude,
        station_latitude=levels[0].latitude,
        levels=levels,
    )


def to_float(value: str | None) -> float | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() in {"nan", "null", "none", "-"}:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def to_bounded_float(
    value: str | None,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    parsed = to_float(value)
    if parsed is None:
        return None
    if minimum is not None and parsed < minimum:
        return None
    if maximum is not None and parsed > maximum:
        return None
    return parsed


def to_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
