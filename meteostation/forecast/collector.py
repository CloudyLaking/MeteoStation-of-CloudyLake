"""Automatic ECMWF IFS/AIFS Open Data cycle collector."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .retriever import retrieve_ecmwf_forecast
from .fast_store import convert_forecast_grib, is_fast_store


ForecastModel = Literal["ifs", "aifs"]
ForecastCycle = Literal["00", "06", "12", "18"]
_CYCLE_PATTERN = re.compile(
    r"^(?P<model>ifs|aifs)_(?P<date>\d{8})_(?P<hour>\d{2})z_"
)


class ForecastCollectorConfig(BaseModel):
    """Runtime policy for the global Open Data forecast cache."""

    poll_interval_seconds: int = Field(default=300, ge=60)
    retry_interval_minutes: int = Field(default=1, ge=1, le=180)
    request_spacing_seconds: float = Field(default=5, ge=0, le=60)
    retain_complete_cycles: int = Field(default=8, ge=1, le=32)
    minimum_free_disk_gb: float = Field(default=3, ge=2, le=1000)
    download_reserve_gb: float = Field(default=3, ge=1, le=100)
    source: Literal["ecmwf", "aws", "azure", "google"] = "aws"
    cycles: list[ForecastCycle] = ["00", "06", "12", "18"]
    models: list[ForecastModel] = ["ifs", "aifs"]
    convert_to_fast_store: bool = True
    discard_grib_after_conversion: bool = True


class ForecastCollector:
    """Monitor four daily cycles and retain the latest complete eight."""

    def __init__(
        self,
        *,
        config: ForecastCollectorConfig,
        cache_root: Path,
        state_path: Path,
    ) -> None:
        self.config = config
        self.cache_root = Path(cache_root)
        self.state_path = Path(state_path)

    async def run_once(
        self,
        reference_time: datetime | None = None,
    ) -> dict[str, object]:
        now = _normalize_utc(reference_time or datetime.now(timezone.utc))
        state = _read_json(self.state_path, default={"items": {}})
        items = state.setdefault("items", {})
        summary: dict[str, object] = {
            "started_at": now.isoformat(),
            "completed": 0,
            "cached": 0,
            "deferred": 0,
            "failed": 0,
            "cycles": [],
        }

        summary["removed_stale_partials"] = remove_stale_partial_downloads(
            self.cache_root / "ecmwf_forecast",
            older_than=now - timedelta(hours=6),
        )
        free_bytes = shutil.disk_usage(self.cache_root).free
        required_bytes = int(
            (
                self.config.minimum_free_disk_gb
                + self.config.download_reserve_gb
            )
            * 1024**3
        )
        if free_bytes < required_bytes and self.config.retain_complete_cycles > 1:
            # Rotate out the oldest complete pair before downloading its
            # replacement. Otherwise a full one-day cache can deadlock: the
            # download reserve is unavailable until pruning, while pruning
            # previously happened only after the attempted download.
            summary["pre_download_rotation"] = {
                model: prune_forecast_cycles(
                    self.cache_root / "ecmwf_forecast" / model,
                    keep=self.config.retain_complete_cycles - 1,
                )
                for model in self.config.models
            }

        candidates = recent_forecast_cycles(
            reference_time=now,
            cycles=self.config.cycles,
            count=self.config.retain_complete_cycles + len(self.config.cycles),
        )
        complete_for_model = {
            model: 0
            for model in self.config.models
        }
        storage_blocked = False
        for initialized_at in candidates:
            for model in self.config.models:
                if (
                    complete_for_model[model]
                    >= self.config.retain_complete_cycles
                ):
                    continue
                key = f"{model}|{initialized_at.isoformat()}"
                item = items.get(key, {})
                before = _cycle_is_complete(
                    self.cache_root,
                    model,
                    initialized_at,
                    require_fast=self.config.convert_to_fast_store,
                )
                if before:
                    complete_for_model[model] += 1
                    summary["cached"] = int(summary["cached"]) + 1
                    continue

                retry_at = _parse_datetime(item.get("next_retry_at"))
                if retry_at is not None and retry_at > now:
                    summary["deferred"] = int(summary["deferred"]) + 1
                    continue

                free_bytes = shutil.disk_usage(self.cache_root).free
                required_bytes = int(
                    (
                        self.config.minimum_free_disk_gb
                        + self.config.download_reserve_gb
                    )
                    * 1024**3
                )
                if free_bytes < required_bytes:
                    summary["storage_blocked"] = {
                        "free_gb": round(free_bytes / 1024**3, 2),
                        "minimum_free_gb": self.config.minimum_free_disk_gb,
                        "download_reserve_gb": self.config.download_reserve_gb,
                    }
                    summary["deferred"] = int(summary["deferred"]) + 1
                    storage_blocked = True
                    break

                try:
                    surface, pressure = await asyncio.to_thread(
                        retrieve_ecmwf_forecast,
                        initialized_at=initialized_at,
                        cache_root=self.cache_root,
                        model=model,
                        source=self.config.source,
                        backend="open-data",
                    )
                    if not surface.exists() or not pressure.exists():
                        raise RuntimeError("forecast cycle cache is incomplete")
                    if self.config.convert_to_fast_store:
                        surface = await asyncio.to_thread(
                            _convert_and_optionally_discard,
                            surface,
                            kind="surface",
                            discard_grib=self.config.discard_grib_after_conversion,
                        )
                        pressure = await asyncio.to_thread(
                            _convert_and_optionally_discard,
                            pressure,
                            kind="pressure",
                            discard_grib=self.config.discard_grib_after_conversion,
                        )
                    completed_at = datetime.now(timezone.utc)
                    items[key] = {
                        "status": "complete",
                        "model": model,
                        "initialized_at": initialized_at.isoformat(),
                        "completed_at": completed_at.isoformat(),
                        "surface_bytes": surface.stat().st_size,
                        "pressure_bytes": pressure.stat().st_size,
                    }
                    complete_for_model[model] += 1
                    summary["completed"] = int(summary["completed"]) + 1
                    summary["cycles"].append(items[key])
                except Exception as exc:
                    retry_at = datetime.now(timezone.utc) + timedelta(
                        minutes=self.config.retry_interval_minutes
                    )
                    items[key] = {
                        "status": "waiting",
                        "model": model,
                        "initialized_at": initialized_at.isoformat(),
                        "last_attempt_at": datetime.now(timezone.utc).isoformat(),
                        "next_retry_at": retry_at.isoformat(),
                        "message": str(exc),
                    }
                    summary["failed"] = int(summary["failed"]) + 1
                finally:
                    state["updated_at"] = datetime.now(timezone.utc).isoformat()
                    state["last_run"] = summary
                    _write_json_atomic(self.state_path, state)

                if self.config.request_spacing_seconds:
                    await asyncio.sleep(self.config.request_spacing_seconds)
            if storage_blocked:
                break

        removed: dict[str, list[str]] = {}
        for model in self.config.models:
            removed[model] = prune_forecast_cycles(
                self.cache_root / "ecmwf_forecast" / model,
                keep=self.config.retain_complete_cycles,
            )
        summary["removed_cycles"] = removed
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        state["updated_at"] = summary["finished_at"]
        state["last_run"] = summary
        _write_json_atomic(self.state_path, state)
        return summary

    async def run_forever(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self.config.poll_interval_seconds)


def load_forecast_collector_config(path: Path) -> ForecastCollectorConfig:
    return ForecastCollectorConfig.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def recent_forecast_cycles(
    *,
    reference_time: datetime,
    cycles: list[ForecastCycle],
    count: int,
) -> list[datetime]:
    """Return the newest *count* cycle initializations, newest first."""
    reference_time = _normalize_utc(reference_time)
    candidates: list[datetime] = []
    day_offset = 0
    while len(candidates) < count:
        candidate_date = reference_time.date() - timedelta(days=day_offset)
        for cycle in cycles:
            candidate = datetime.combine(
                candidate_date,
                time(hour=int(cycle)),
                tzinfo=timezone.utc,
            )
            if candidate <= reference_time:
                candidates.append(candidate)
        day_offset += 1
    return sorted(set(candidates), reverse=True)[:count]


def prune_forecast_cycles(model_root: Path, *, keep: int) -> list[str]:
    """Delete files belonging to complete cycles older than the newest *keep*."""
    model_root = Path(model_root)
    if not model_root.is_dir():
        return []

    grouped: dict[datetime, list[Path]] = {}
    surfaces = [
        *model_root.rglob("*_forecast_surface_144h_*hourly.grib2"),
        *model_root.rglob("*_forecast_surface_144h_*hourly.fast.nc"),
    ]
    for surface in surfaces:
        match = _CYCLE_PATTERN.match(surface.name)
        if match is None:
            continue
        cycle = datetime.strptime(
            match.group("date") + match.group("hour"),
            "%Y%m%d%H",
        ).replace(tzinfo=timezone.utc)
        prefix = (
            f"{match.group('model')}_{match.group('date')}_"
            f"{match.group('hour')}z_"
        )
        pressure = [
            *surface.parent.glob(
                f"{prefix}forecast_pressure_144h_*hourly.grib2"
            ),
            *surface.parent.glob(
                f"{prefix}forecast_pressure_144h_*hourly.fast.nc"
            ),
        ]
        if not pressure:
            continue
        grouped[cycle] = list(surface.parent.glob(f"{prefix}*"))

    removed: list[str] = []
    for cycle in sorted(grouped, reverse=True)[keep:]:
        for path in grouped[cycle]:
            if path.is_file():
                path.unlink()
        removed.append(cycle.isoformat())

    directories = sorted(
        (path for path in model_root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            pass
    return removed


def remove_stale_partial_downloads(
    forecast_root: Path,
    *,
    older_than: datetime,
) -> list[str]:
    """Remove abandoned resumable fragments after a collector interruption."""
    root = Path(forecast_root).resolve()
    if not root.is_dir():
        return []
    cutoff = _normalize_utc(older_than).timestamp()
    removed: list[str] = []
    for pattern in ("*.part", "*.part.resume"):
        for path in root.rglob(pattern):
            resolved = path.resolve()
            if root not in resolved.parents or not resolved.is_file():
                continue
            try:
                if resolved.stat().st_mtime >= cutoff:
                    continue
                resolved.unlink()
                removed.append(resolved.relative_to(root).as_posix())
            except OSError:
                continue
    return removed


def _cycle_is_complete(
    cache_root: Path,
    model: str,
    initialized_at: datetime,
    *,
    require_fast: bool = False,
) -> bool:
    directory = (
        Path(cache_root)
        / "ecmwf_forecast"
        / model
        / f"{initialized_at:%Y}"
        / f"{initialized_at:%m}"
        / f"{initialized_at:%d}"
    )
    prefix = f"{model}_{initialized_at:%Y%m%d}_{initialized_at:%H}z_"
    suffixes = ("fast.nc",) if require_fast else ("grib2", "fast.nc")
    surface = [
        item
        for suffix in suffixes
        for item in directory.glob(
            f"{prefix}forecast_surface_144h_*hourly.{suffix}"
        )
    ]
    pressure = [
        item
        for suffix in suffixes
        for item in directory.glob(
            f"{prefix}forecast_pressure_144h_*hourly.{suffix}"
        )
    ]
    return bool(surface and pressure)


def _convert_and_optionally_discard(
    path: Path,
    *,
    kind: Literal["surface", "pressure"],
    discard_grib: bool,
) -> Path:
    source = Path(path)
    converted = convert_forecast_grib(source, kind=kind)
    if discard_grib and not is_fast_store(source):
        source.unlink(missing_ok=True)
        for index_path in source.parent.glob(f"{source.name}.*.idx"):
            index_path.unlink(missing_ok=True)
    return converted


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return _normalize_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def _read_json(path: Path, *, default: dict[str, object]) -> dict[str, object]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
