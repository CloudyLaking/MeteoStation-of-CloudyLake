from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, HttpUrl

from .collector import (
    CollectorConfig,
    CollectorStation,
    SoundingCollector,
    load_json,
    recent_cycles,
    write_json_atomic,
)


class GlobalCollectorConfig(BaseModel):
    poll_interval_seconds: int = Field(default=60, ge=60)
    lookback_hours: int = Field(default=72, ge=24, le=168)
    request_spacing_seconds: float = Field(default=0.8, ge=0.2, le=60)
    request_timeout_seconds: float = Field(default=8, ge=3, le=60)
    retention_days: int = Field(default=3, ge=1, le=30)
    active_since_year: int = Field(default=2025, ge=1900)
    catalog_refresh_hours: int = Field(default=1, ge=1, le=168)
    station_catalog_url: HttpUrl
    wyoming_inventory_url: HttpUrl = HttpUrl(
        "https://weather.uwyo.edu/wsgi/sounding_json"
    )
    cycles: list[str] = ["00", "12"]
    preserve_station_ids: list[str] = ["58362"]


def load_global_collector_config(path: Path) -> GlobalCollectorConfig:
    return GlobalCollectorConfig.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def parse_igra_station_catalog(
    text: str,
    *,
    active_since_year: int,
) -> list[CollectorStation]:
    """Convert NOAA IGRA's fixed-width station list to WMO stations."""
    stations: dict[str, CollectorStation] = {}
    for line in text.splitlines():
        if len(line) < 81:
            continue
        station_id = line[:11][-5:]
        last_year = line[77:81].strip()
        if (
            not station_id.isdigit()
            or station_id == "99999"
            or not last_year.isdigit()
            or int(last_year) < active_since_year
        ):
            continue
        name = line[41:71].strip() or f"WMO {station_id}"
        stations[station_id] = CollectorStation(
            wmo_id=station_id,
            name=name,
            name_en=name,
            enabled=True,
            priority=100 if station_id == "58362" else 0,
        )
    return sorted(stations.values(), key=lambda item: item.wmo_id)


async def load_global_stations(
    config: GlobalCollectorConfig,
    *,
    cache_path: Path,
    reference_time: datetime | None = None,
) -> tuple[
    list[CollectorStation],
    dict[str, list[str]],
    dict[str, dict[str, str]],
]:
    cached = load_json(cache_path, default={})
    fetched_at = cached.get("fetched_at")
    if isinstance(fetched_at, str):
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at)
        except ValueError:
            age = timedelta.max
        if (
            age < timedelta(hours=config.catalog_refresh_hours)
            and cached.get("source_kind") == "wyoming_inventory"
            and isinstance(cached.get("station_ids_by_cycle"), dict)
            and isinstance(cached.get("station_sources_by_cycle"), dict)
        ):
            return (
                [
                    CollectorStation.model_validate(item)
                    for item in cached.get("stations", [])
                ],
                {
                    key: [str(station_id) for station_id in value]
                    for key, value in cached["station_ids_by_cycle"].items()
                    if isinstance(value, list)
                },
                {
                    key: {
                        str(station_id): str(source)
                        for station_id, source in value.items()
                    }
                    for key, value in cached[
                        "station_sources_by_cycle"
                    ].items()
                    if isinstance(value, dict)
                },
            )

    now = reference_time or datetime.now(timezone.utc)
    requested_cycles = recent_cycles(
        reference_time=now,
        cycles=config.cycles,
        lookback_hours=config.lookback_hours,
    )
    requested_cycle_keys = {
        valid_at.isoformat() for valid_at in requested_cycles
    }
    station_records: dict[str, CollectorStation] = {
        station.wmo_id: station
        for station in (
            CollectorStation.model_validate(item)
            for item in cached.get("stations", [])
        )
    }
    station_ids_by_cycle: dict[str, list[str]] = {
        key: [str(station_id) for station_id in value]
        for key, value in cached.get("station_ids_by_cycle", {}).items()
        if key in requested_cycle_keys and isinstance(value, list)
    }
    station_sources_by_cycle: dict[str, dict[str, str]] = {
        key: {
            str(station_id): str(source)
            for station_id, source in value.items()
        }
        for key, value in cached.get(
            "station_sources_by_cycle",
            {},
        ).items()
        if key in requested_cycle_keys and isinstance(value, dict)
    }
    headers = {"User-Agent": "CloudyLake-Observatory/2.1.1"}
    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        headers=headers,
    ) as client:
        async def fetch_inventory(valid_at: datetime):
            try:
                response = await client.get(
                    str(config.wyoming_inventory_url),
                    params={
                        "datetime": valid_at.strftime("%Y-%m-%d %H:%M:%S")
                    },
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError):
                return valid_at, None
            return valid_at, payload

        inventories = await asyncio.gather(
            *(fetch_inventory(valid_at) for valid_at in requested_cycles)
        )
        for valid_at, payload in inventories:
            if payload is None:
                continue
            station_ids: set[str] = set()
            station_sources: dict[str, str] = {}
            for item in payload.get("stations", []):
                station_id = str(item.get("stationid", "")).strip()
                if len(station_id) != 5 or not station_id.isdigit():
                    continue
                station_ids.add(station_id)
                station_sources[station_id] = (
                    str(item.get("src", "UNKNOWN")).strip().upper()
                    or "UNKNOWN"
                )
                name = str(item.get("name", "")).strip() or f"WMO {station_id}"
                station_records[station_id] = CollectorStation(
                    wmo_id=station_id,
                    name=name,
                    name_en=name,
                    enabled=True,
                    priority=100 if station_id == "58362" else 0,
                )
            station_ids_by_cycle[valid_at.isoformat()] = sorted(station_ids)
            station_sources_by_cycle[valid_at.isoformat()] = station_sources

    if not station_ids_by_cycle:
        async with httpx.AsyncClient(
            timeout=60,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = await client.get(str(config.station_catalog_url))
            response.raise_for_status()
        fallback_stations = parse_igra_station_catalog(
            response.text,
            active_since_year=config.active_since_year,
        )
        fallback_ids = [station.wmo_id for station in fallback_stations]
        station_ids_by_cycle = {
            valid_at.isoformat(): fallback_ids
            for valid_at in requested_cycles
        }
        station_sources_by_cycle = {
            valid_at.isoformat(): {
                station_id: "UNKNOWN"
                for station_id in fallback_ids
            }
            for valid_at in requested_cycles
        }
        station_records = {
            station.wmo_id: station for station in fallback_stations
        }

    stations = sorted(
        station_records.values(),
        key=lambda station: station.wmo_id,
    )
    write_json_atomic(
        cache_path,
        {
            "source": str(config.wyoming_inventory_url),
            "source_kind": "wyoming_inventory",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "station_count": len(stations),
            "stations": [
                station.model_dump(mode="json") for station in stations
            ],
            "station_ids_by_cycle": station_ids_by_cycle,
            "station_sources_by_cycle": station_sources_by_cycle,
        },
    )
    return stations, station_ids_by_cycle, station_sources_by_cycle


def prune_global_archive(
    raw_data_root: Path,
    state_path: Path,
    *,
    retention_days: int,
    preserve_station_ids: set[str],
    reference_time: datetime | None = None,
) -> dict[str, int]:
    now = reference_time or datetime.now(timezone.utc)
    cutoff = now.date() - timedelta(days=retention_days)
    wyoming_root = (Path(raw_data_root).resolve() / "wyoming").resolve()
    removed_files = 0
    removed_directories = 0
    if wyoming_root.exists():
        for year_dir in wyoming_root.iterdir():
            for month_dir in year_dir.iterdir() if year_dir.is_dir() else []:
                for day_dir in month_dir.iterdir() if month_dir.is_dir() else []:
                    try:
                        archived_date = datetime.strptime(
                            f"{year_dir.name}-{month_dir.name}-{day_dir.name}",
                            "%Y-%m-%d",
                        ).date()
                    except ValueError:
                        continue
                    resolved_day = day_dir.resolve()
                    if (
                        archived_date >= cutoff
                        or wyoming_root not in resolved_day.parents
                    ):
                        continue
                    for path in resolved_day.iterdir():
                        if path.name[:5] in preserve_station_ids:
                            continue
                        if path.is_file():
                            path.unlink()
                            removed_files += 1
                    if not any(resolved_day.iterdir()):
                        shutil.rmtree(resolved_day)
                        removed_directories += 1

    state = load_json(state_path, default={"items": {}})
    items = state.get("items", {})
    if isinstance(items, dict):
        state["items"] = {
            key: value
            for key, value in items.items()
            if key[:5] in preserve_station_ids
            or _state_item_is_recent(key, cutoff)
        }
        write_json_atomic(state_path, state)
    return {
        "removed_files": removed_files,
        "removed_directories": removed_directories,
    }


def _state_item_is_recent(key: str, cutoff) -> bool:
    try:
        return datetime.fromisoformat(key.split("|", 1)[1]).date() >= cutoff
    except (IndexError, ValueError):
        return True


async def run_global_collector(
    *,
    config_path: Path,
    project_root: Path,
    once: bool = False,
) -> None:
    global_config = load_global_collector_config(config_path)
    state_root = project_root / "data" / "state"
    while True:
        (
            stations,
            station_ids_by_cycle,
            station_sources_by_cycle,
        ) = await load_global_stations(
            global_config,
            cache_path=state_root / "global_sounding_stations.json",
        )
        collector = SoundingCollector(
            config=CollectorConfig(
                poll_interval_seconds=global_config.poll_interval_seconds,
                lookback_hours=global_config.lookback_hours,
                request_spacing_seconds=global_config.request_spacing_seconds,
                generate_static_products=False,
                cycles=global_config.cycles,
                stations=stations,
                station_ids_by_cycle=station_ids_by_cycle,
                station_sources_by_cycle=station_sources_by_cycle,
            ),
            raw_data_root=project_root / "data" / "raw",
            product_root=project_root / "data" / "products",
            state_path=state_root / "global_sounding_collector.json",
            font_path=project_root / "MiSans VF.ttf",
        )
        collector.client.timeout_seconds = global_config.request_timeout_seconds
        summary = await collector.run_once()
        summary["retention"] = prune_global_archive(
            project_root / "data" / "raw",
            state_root / "global_sounding_collector.json",
            retention_days=global_config.retention_days,
            preserve_station_ids=set(global_config.preserve_station_ids),
        )
        print(json.dumps(summary, ensure_ascii=False))
        if once:
            return
        await asyncio.sleep(global_config.poll_interval_seconds)
