"""Worldwide WMO station directory for OGIMET SYNOP lookups.

The table is generated from the NOAA IGRA2 global station list (see
tools/build_world_stations.py) and stored as config/world_stations.json.
Chinese national stations remain in station_registry; this module only adds
stations outside China. Any 5-digit WMO id can still be queried through
OGIMET even if it is missing from the directory — it will simply show the
bare id instead of a name.
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


WORLD_STATIONS_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "world_stations.json"
)


@dataclass(frozen=True)
class WorldStation:
    wmo_id: str
    name: str
    country_code: str
    latitude: float
    longitude: float
    elevation_m: float

    @property
    def display_name(self) -> str:
        # IGRA names are uppercase and truncated to 30 chars; title-case them
        # for display while keeping parenthesised suffixes like "(UA)" intact.
        def _keep_parenthesis(match: re.Match[str]) -> str:
            return f"({match.group(1)})"

        return re.sub(r"\(([^)]+)\)", _keep_parenthesis, self.name.title())

    def as_dict(self) -> dict[str, object]:
        return {
            "wmo_id": self.wmo_id,
            "name": self.name,
            "display_name": self.display_name,
            "country_code": self.country_code,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation_m": self.elevation_m,
            "source": "world",
        }


@lru_cache(maxsize=1)
def world_station_records() -> tuple[WorldStation, ...]:
    if not WORLD_STATIONS_PATH.exists():
        return ()
    try:
        with WORLD_STATIONS_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return ()
    return tuple(
        WorldStation(
            wmo_id=item["wmo_id"],
            name=item["name"],
            country_code=item.get("country_code", ""),
            latitude=float(item.get("latitude", 0.0)),
            longitude=float(item.get("longitude", 0.0)),
            elevation_m=float(item.get("elevation_m", 0.0)),
        )
        for item in data
        if isinstance(item, dict) and item.get("wmo_id")
    )


def resolve_world_station(query: str) -> WorldStation | None:
    """Resolve a 5-digit WMO id (or exact name) to a world station."""
    normalized = query.strip().casefold()
    if not normalized:
        return None
    if re.fullmatch(r"\d{5}", normalized):
        for station in world_station_records():
            if station.wmo_id == normalized:
                return station
        return None
    for station in world_station_records():
        if station.name.casefold() == normalized:
            return station
    return None


def search_world_stations(query: str, *, limit: int = 10) -> list[WorldStation]:
    normalized = query.strip().casefold()
    if not normalized:
        return []
    exact: list[WorldStation] = []
    partial: list[WorldStation] = []
    for station in world_station_records():
        keys = (station.wmo_id.casefold(), station.name.casefold(), station.display_name.casefold())
        if normalized in keys:
            exact.append(station)
        elif any(normalized in key for key in keys):
            partial.append(station)
    return (exact + partial)[:limit]
