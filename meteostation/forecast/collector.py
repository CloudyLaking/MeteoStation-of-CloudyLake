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

from .retriever import FORECAST_PRESSURE_LEVELS, retrieve_ecmwf_forecast
from .fast_store import (
    convert_forecast_grib,
    fast_store_has_pressure_levels,
    is_fast_store,
)
from .manifest import (
    CycleEntry,
    CycleLease,
    ForecastManifest,
    LeaseUnavailable,
    build_cycle_entry,
    cycle_directory,
    validate_cycle_files,
)


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
    publish_manifest: bool = True
    retire_grace_hours: float = Field(default=24, ge=1, le=168)
    max_stale_hours: dict[str, float] = Field(
        default_factory=lambda: {"ifs": 18.0, "aifs": 30.0}
    )


class ForecastCollector:
    """Monitor daily cycles; publish validated ones through the manifest."""

    def __init__(
        self,
        *,
        config: ForecastCollectorConfig,
        cache_root: Path,
        state_path: Path,
        manifest_path: Path | None = None,
    ) -> None:
        self.config = config
        self.cache_root = Path(cache_root)
        self.state_path = Path(state_path)
        self.manifest = ForecastManifest(
            path=manifest_path
            or (Path(state_path).parent / "manifest" / "current.json"),
            cache_root=self.cache_root,
            retire_grace_hours=config.retire_grace_hours,
        )

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
            # replacement.  The manifest current/previous cycles and the
            # single last complete cycle are always protected so a public
            # read never loses its file, and a storage shortage can never
            # remove the only usable cycle.
            summary["pre_download_rotation"] = {
                model: prune_forecast_cycles(
                    self.cache_root / "ecmwf_forecast" / model,
                    keep=max(1, self.config.retain_complete_cycles - 1),
                    protected=self._protected_cycles(model),
                )
                for model in self.config.models
            }
            summary["pre_download_free_gb"] = round(
                shutil.disk_usage(self.cache_root).free / 1024**3, 2
            )

        candidates = recent_forecast_cycles(
            reference_time=now,
            cycles=self.config.cycles,
            count=self.config.retain_complete_cycles,
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
                    if self.config.convert_to_fast_store:
                        # Only publish a cycle that passes the full
                        # filesystem validation (variables, steps, levels,
                        # grid).  The web reads resolve through this
                        # validation, never through this state JSON alone.
                        validation = await asyncio.to_thread(
                            validate_cycle_files,
                            self.cache_root,
                            model,
                            initialized_at,
                            require_fast=True,
                        )
                        if not validation["ok"]:
                            raise RuntimeError(
                                "cycle validation failed: "
                                + "; ".join(
                                    str(error) for error in validation["errors"]
                                )
                            )
                    items[key] = {
                        "status": "complete",
                        "model": model,
                        "initialized_at": initialized_at.isoformat(),
                        "completed_at": completed_at.isoformat(),
                        "surface_bytes": surface.stat().st_size,
                        "pressure_bytes": pressure.stat().st_size,
                        "validated": True,
                    }
                    if self.config.publish_manifest:
                        self.manifest.publish(
                            model,
                            CycleEntry(
                                initialized_at=initialized_at,
                                validated_at=completed_at,
                                surface_path=surface.relative_to(
                                    self.cache_root
                                ).as_posix(),
                                pressure_path=pressure.relative_to(
                                    self.cache_root
                                ).as_posix(),
                                surface_bytes=surface.stat().st_size,
                                pressure_bytes=pressure.stat().st_size,
                            ),
                        )
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
        retired_now: dict[str, list[str]] = {}
        if self.config.publish_manifest:
            summary["bootstrap"] = self._bootstrap_manifest()
        for model in self.config.models:
            removed[model] = prune_forecast_cycles(
                self.cache_root / "ecmwf_forecast" / model,
                keep=self.config.retain_complete_cycles,
                protected=self._protected_cycles(model),
                manifest=(
                    self.manifest if self.config.publish_manifest else None
                ),
            )
            if self.config.publish_manifest:
                retired_now[model] = self._retire_due_cycles(model)
        summary["removed_cycles"] = removed
        if self.config.publish_manifest:
            summary["retired_after_grace"] = retired_now
            summary["manifest"] = self.manifest.load().get("cycles", {})
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        state["updated_at"] = summary["finished_at"]
        state["last_run"] = summary
        _write_json_atomic(self.state_path, state)
        return summary

    def _protected_cycles(self, model: str) -> set[datetime]:
        """Cycles that must never be pruned: manifest current/previous."""
        protected: set[datetime] = set()
        slots = self.manifest.cycles().get(model, {})
        for slot in ("current", "previous"):
            entry = slots.get(slot)
            if entry is not None:
                protected.add(entry.initialized_at)
        return protected

    def _bootstrap_manifest(self) -> dict[str, object]:
        """Publish the newest validated on-disk cycle when manifest is empty.

        This closes the upgrade gap: right after deployment the manifest does
        not exist yet, and web reads must not fall back to a state JSON that
        may claim complete cycles whose files are gone.
        """
        published: dict[str, object] = {}
        slots = self.manifest.cycles()
        for model in self.config.models:
            if slots.get(model, {}).get("current") is not None:
                continue
            newest: tuple[datetime, CycleEntry] | None = None
            model_root = self.cache_root / "ecmwf_forecast" / model
            if model_root.is_dir():
                for surface in model_root.rglob(
                    "*_forecast_surface_144h_*hourly.fast.nc"
                ):
                    match = _CYCLE_PATTERN.match(surface.name)
                    if match is None or match.group("model") != model:
                        continue
                    initialized_at = datetime.strptime(
                        match.group("date") + match.group("hour"),
                        "%Y%m%d%H",
                    ).replace(tzinfo=timezone.utc)
                    if newest is not None and initialized_at <= newest[0]:
                        continue
                    entry = build_cycle_entry(
                        self.cache_root,
                        model,
                        initialized_at,
                        require_fast=True,
                    )
                    if entry is not None:
                        newest = (initialized_at, entry)
            if newest is not None:
                self.manifest.publish(model, newest[1])
                published[model] = newest[0].isoformat()
        return published

    def _retire_due_cycles(self, model: str) -> list[str]:
        """Delete files whose retirement grace period has fully expired."""
        due = self.manifest.due_retired_paths()
        removed: list[str] = []
        for path in due:
            match = _CYCLE_PATTERN.match(path.name)
            if match is None or match.group("model") != model:
                continue
            initialized_at = datetime.strptime(
                match.group("date") + match.group("hour"),
                "%Y%m%d%H",
            ).replace(tzinfo=timezone.utc)
            parent = path.parent
            try:
                with CycleLease(
                    self.cache_root,
                    model,
                    initialized_at,
                    exclusive=True,
                    blocking=False,
                ):
                    for sibling in list(parent.glob(
                        f"{model}_{match.group('date')}_{match.group('hour')}z_*"
                    )):
                        if sibling.is_file():
                            sibling.unlink()
                            removed.append(sibling.as_posix())
                    try:
                        parent.rmdir()
                    except OSError:
                        pass
            except (LeaseUnavailable, OSError):
                continue
        return removed

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


def prune_forecast_cycles(
    model_root: Path,
    *,
    keep: int,
    protected: set[datetime] | None = None,
    manifest: ForecastManifest | None = None,
) -> list[str]:
    """Retire (or delete) complete cycles older than the newest *keep*.

    ``protected`` cycles (manifest current/previous) are never touched.  When
    a manifest is supplied, normal rotation only *marks* the cycle retired;
    actual deletion is delayed until its grace period expires.  During a
    storage shortage the caller omits the manifest to reclaim space at once
    (still protecting manifest cycles and the last complete cycle).  Every
    deletion runs under an exclusive cross-process lease so concurrent web
    reads either finish before deletion or never see the cycle disappear
    mid-request.
    """
    model_root = Path(model_root)
    protected = protected or set()
    if not model_root.is_dir():
        return []

    model_name = model_root.name
    lease_root = model_root.parent
    cache_root = model_root.parent.parent
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

    retired: list[str] = []
    for cycle in sorted(grouped, reverse=True)[keep:]:
        if cycle in protected:
            continue
        if manifest is not None:
            # Delayed cleanup: record retirement, delete only after grace.
            manifest.mark_retired(
                {
                    f"{model_name}|{cycle.isoformat()}": sorted(
                        grouped[cycle]
                    )[0].relative_to(cache_root).as_posix()
                }
            )
            retired.append(cycle.isoformat())
            continue
        try:
            with CycleLease(
                lease_root,
                model_name,
                cycle,
                exclusive=True,
                blocking=False,
            ):
                for path in grouped[cycle]:
                    if path.is_file():
                        path.unlink()
        except LeaseUnavailable:
            # A public read still holds the shared lease; retry next cycle.
            continue
        retired.append(cycle.isoformat())

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
    return retired


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
    if not surface or not pressure:
        return False
    if require_fast and not any(
        fast_store_has_pressure_levels(item, FORECAST_PRESSURE_LEVELS)
        for item in pressure
    ):
        return False
    return True


def _convert_and_optionally_discard(
    path: Path,
    *,
    kind: Literal["surface", "pressure"],
    discard_grib: bool,
) -> Path:
    source = Path(path)
    if kind == "pressure" and not is_fast_store(source):
        existing = source.with_name(f"{source.name[:-6]}.fast.nc")
        if existing.exists() and not fast_store_has_pressure_levels(
            existing,
            FORECAST_PRESSURE_LEVELS,
        ):
            # The complete GRIB is already durable at this point, so replacing
            # the old derived cache here keeps the public query path available
            # throughout the much longer network download.
            existing.unlink()
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
