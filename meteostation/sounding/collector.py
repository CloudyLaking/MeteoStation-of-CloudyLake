import asyncio
import json
import os
import shutil
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .models import SoundingProduct
from .render import (
    RENDERER_VERSION,
    render_skewt_quicklook,
    render_stuve_quicklook,
)
from .wyoming import WyomingSoundingClient, WyomingSoundingError


class CollectorStation(BaseModel):
    wmo_id: str = Field(pattern=r"^\d{5}$")
    name: str
    name_en: str
    enabled: bool = True
    priority: int = 0


class CollectorConfig(BaseModel):
    poll_interval_seconds: int = Field(default=300, ge=60)
    lookback_hours: int = Field(default=24, ge=12, le=168)
    request_spacing_seconds: float = Field(default=2, ge=0, le=60)
    generate_static_products: bool = False
    cycles: list[Literal["00", "12"]] = ["00", "12"]
    stations: list[CollectorStation]
    station_ids_by_cycle: dict[str, list[str]] | None = None
    station_sources_by_cycle: dict[str, dict[str, str]] | None = None


class SoundingCollector:
    def __init__(
        self,
        *,
        config: CollectorConfig,
        raw_data_root: Path,
        product_root: Path,
        state_path: Path,
        font_path: Path | None = None,
    ) -> None:
        self.config = config
        self.client = WyomingSoundingClient(raw_data_root)
        self.product_root = Path(product_root)
        self.state_path = Path(state_path)
        self.font_path = font_path
        self.catalog_path = self.product_root / "soundings" / "catalog.json"

    async def run_once(
        self,
        reference_time: datetime | None = None,
    ) -> dict[str, object]:
        now = normalize_utc(reference_time or datetime.now(timezone.utc))
        cleared_products = False
        if self.config.generate_static_products:
            cleared_products = prepare_product_store(
                self.product_root,
                renderer_version=RENDERER_VERSION,
            )
        state = load_json(self.state_path, default={"items": {}})
        items = state.setdefault("items", {})
        summary = {
            "started_at": now.isoformat(),
            "renderer_version": RENDERER_VERSION,
            "generate_static_products": self.config.generate_static_products,
            "cleared_outdated_products": cleared_products,
            "completed": 0,
            "skipped": 0,
            "deferred": 0,
            "failed": 0,
            "products": [],
        }

        stations = sorted(
            (station for station in self.config.stations if station.enabled),
            key=lambda station: station.priority,
            reverse=True,
        )
        cycles = recent_cycles(
            reference_time=now,
            cycles=self.config.cycles,
            lookback_hours=self.config.lookback_hours,
        )

        tasks: list[tuple[datetime, CollectorStation]] = []
        for valid_at in cycles:
            cycle_stations = stations
            if self.config.station_ids_by_cycle is not None:
                station_ids = set(
                    self.config.station_ids_by_cycle.get(
                        valid_at.isoformat(),
                        [],
                    )
                )
                cycle_stations = [
                    station
                    for station in stations
                    if station.wmo_id in station_ids
                ]
            tasks.extend(
                (valid_at, station)
                for station in cycle_stations
            )

        # A restart must not let retries in the newest cycle starve station
        # times that have never been attempted in older cycles. Python's
        # stable sort preserves cycle/station priority within both groups.
        tasks.sort(
            key=lambda task: (
                items.get(
                    collector_item_key(task[1].wmo_id, task[0]),
                    {},
                ).get("status")
                == "waiting"
            )
        )

        for valid_at, station in tasks:
            key = collector_item_key(station.wmo_id, valid_at)
            item_state = items.get(key, {})

            if not self.config.generate_static_products and item_state.get(
                "status"
            ) == "archived":
                summary["skipped"] += 1
                continue

            if self.config.generate_static_products and product_exists(
                self.product_root, station.wmo_id, valid_at
            ):
                item_state.update(
                    {
                        "status": "complete",
                        "station_name": station.name,
                        "valid_at": valid_at.isoformat(),
                    }
                )
                items[key] = item_state
                summary["skipped"] += 1
                continue

            retry_at = parse_optional_datetime(item_state.get("next_retry_at"))
            if retry_at is not None and retry_at > now:
                summary["deferred"] += 1
                continue

            try:
                source = "UNKNOWN"
                if self.config.station_sources_by_cycle is not None:
                    source = self.config.station_sources_by_cycle.get(
                        valid_at.isoformat(),
                        {},
                    ).get(station.wmo_id, "UNKNOWN")
                profile = await self.client.get_profile(
                    station_id=station.wmo_id,
                    sounding_date=valid_at.date(),
                    cycle=valid_at.strftime("%H"),
                    source=source,
                )
                products: list[SoundingProduct] = []
                if self.config.generate_static_products:
                    products = [
                            render_skewt_quicklook(
                                profile,
                                product_root=self.product_root,
                                font_path=self.font_path,
                                station_name=station.name_en,
                            ),
                            render_stuve_quicklook(
                                profile,
                                product_root=self.product_root,
                                font_path=self.font_path,
                                station_name=station.name_en,
                            ),
                    ]
                    for product in products:
                        update_product_catalog(self.catalog_path, product)
                item_state = {
                    "status": (
                        "complete"
                        if self.config.generate_static_products
                        else "archived"
                    ),
                    "station_name": station.name,
                    "valid_at": valid_at.isoformat(),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "products": [
                        product.model_dump(mode="json")
                        for product in products
                    ],
                    "attempts": int(item_state.get("attempts", 0)) + 1,
                }
                items[key] = item_state
                summary["completed"] += 1
                summary["products"].extend(
                    product.model_dump(mode="json")
                    for product in products
                )

                if profile.cache_status == "miss":
                    await asyncio.sleep(self.config.request_spacing_seconds)
            except (WyomingSoundingError, ValueError) as exc:
                attempts = int(item_state.get("attempts", 0)) + 1
                retry_minutes = min(5 * (2 ** (attempts - 1)), 60)
                item_state = {
                    "status": "waiting",
                    "station_name": station.name,
                    "valid_at": valid_at.isoformat(),
                    "attempts": attempts,
                    "last_attempt_at": datetime.now(timezone.utc).isoformat(),
                    "next_retry_at": (
                        datetime.now(timezone.utc)
                        + timedelta(minutes=retry_minutes)
                    ).isoformat(),
                    "message": str(exc),
                }
                items[key] = item_state
                summary["failed"] += 1
                await asyncio.sleep(self.config.request_spacing_seconds)
            finally:
                state["updated_at"] = datetime.now(timezone.utc).isoformat()
                state["last_run"] = summary
                write_json_atomic(self.state_path, state)

        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        state["updated_at"] = summary["finished_at"]
        state["last_run"] = summary
        write_json_atomic(self.state_path, state)
        return summary

    async def run_forever(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self.config.poll_interval_seconds)


def load_collector_config(path: Path) -> CollectorConfig:
    raw_config = json.loads(Path(path).read_text(encoding="utf-8"))
    return CollectorConfig.model_validate(raw_config)


def recent_cycles(
    *,
    reference_time: datetime,
    cycles: list[Literal["00", "12"]],
    lookback_hours: int,
) -> list[datetime]:
    reference_time = normalize_utc(reference_time)
    earliest = reference_time - timedelta(hours=lookback_hours)
    candidates: list[datetime] = []

    for day_offset in range((lookback_hours // 24) + 3):
        candidate_date = reference_time.date() - timedelta(days=day_offset)
        for cycle in cycles:
            candidate = datetime.combine(
                candidate_date,
                time(hour=int(cycle)),
                tzinfo=timezone.utc,
            )
            if earliest <= candidate <= reference_time:
                candidates.append(candidate)

    return sorted(set(candidates), reverse=True)


def collector_item_key(station_id: str, valid_at: datetime) -> str:
    return f"{station_id}|{normalize_utc(valid_at).isoformat()}"


def product_exists(
    product_root: Path,
    station_id: str,
    valid_at: datetime,
) -> bool:
    directory = (
        Path(product_root)
        / "soundings"
        / f"{valid_at:%Y}"
        / f"{valid_at:%m}"
        / f"{valid_at:%d}"
    )
    required = [
        directory / f"{station_id}_{valid_at:%H}_skewt.png",
        directory / f"{station_id}_{valid_at:%H}_skewt.json",
        directory / f"{station_id}_{valid_at:%H}_stuve.png",
        directory / f"{station_id}_{valid_at:%H}_stuve.json",
    ]
    return all(path.exists() for path in required)


def prepare_product_store(
    product_root: Path,
    *,
    renderer_version: str,
) -> bool:
    """Clear generated sounding products when their renderer version changes."""
    resolved_root = Path(product_root).resolve()
    sounding_root = (resolved_root / "soundings").resolve()
    if sounding_root.parent != resolved_root:
        raise ValueError("Sounding product directory escaped product_root")

    version_path = sounding_root / ".renderer-version"
    installed_version = (
        version_path.read_text(encoding="utf-8").strip()
        if version_path.exists()
        else None
    )
    cleared = sounding_root.exists() and installed_version != renderer_version

    if cleared:
        shutil.rmtree(sounding_root)

    sounding_root.mkdir(parents=True, exist_ok=True)
    version_path.write_text(f"{renderer_version}\n", encoding="utf-8")
    return cleared


def update_product_catalog(
    catalog_path: Path,
    product: SoundingProduct,
) -> None:
    catalog = load_json(catalog_path, default={"products": []})
    serialized_product = product.model_dump(mode="json")
    products = [
        item
        for item in catalog.get("products", [])
        if not (
            item.get("station_id") == product.station_id
            and item.get("valid_at") == serialized_product["valid_at"]
            and item.get("diagram_type") == product.diagram_type
        )
    ]
    products.append(serialized_product)
    products.sort(
        key=lambda item: item.get("valid_at", ""),
        reverse=True,
    )
    catalog["updated_at"] = datetime.now(timezone.utc).isoformat()
    catalog["products"] = products
    write_json_atomic(catalog_path, catalog)


def load_json(path: Path, *, default: dict[str, object]) -> dict[str, object]:
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_optional_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return normalize_utc(datetime.fromisoformat(value))
    except ValueError:
        return None
