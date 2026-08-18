"""Cross-process forecast-cache manifest, validation and file leases.

The collector publishes complete forecast cycles through an atomically
replaced *manifest* (`data/state/manifest/current.json`).  The web process
never trusts the collector state JSON: every read resolves the cycle through
the manifest and re-validates it against the filesystem.  File leases keep
short-lived web reads safe from collector pruning, and pruning is delayed
until a cycle is both superseded and past its retirement grace period.
"""

from __future__ import annotations

import dataclasses
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

# Cross-process lock on POSIX; no-op fallback elsewhere (development only).
try:
    import fcntl  # type: ignore[import-not-found]

    _POSIX_FLOCK = True
except ImportError:  # pragma: no cover - Windows development fallback
    fcntl = None  # type: ignore[assignment]
    _POSIX_FLOCK = False

from .retriever import FORECAST_PRESSURE_LEVELS

StoreKind = Literal["surface", "pressure"]

# ECMWF Open Data 0.25-degree global grid layout (IFS and AIFS-single).
EXPECTED_LATITUDE_COUNT = 721
EXPECTED_LONGITUDE_COUNT = 1440

SURFACE_STORE_NAMES = ("u10", "v10", "t2m", "d2m", "sp", "msl", "tp", "tcc")
IFS_PRESSURE_STORE_NAMES = ("gh", "t", "r", "u", "v")
AIFS_PRESSURE_STORE_NAMES = ("gh", "t", "q", "u", "v")

_MANIFEST_SCHEMA_VERSION = 1


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def cycle_directory(
    cache_root: Path,
    model: str,
    initialized_at: datetime,
) -> Path:
    return (
        Path(cache_root)
        / "ecmwf_forecast"
        / model
        / f"{initialized_at:%Y}"
        / f"{initialized_at:%m}"
        / f"{initialized_at:%d}"
    )


def cycle_file_prefix(model: str, initialized_at: datetime) -> str:
    return f"{model}_{initialized_at:%Y%m%d}_{initialized_at:%H}z_"


def _locate_store(
    directory: Path,
    prefix: str,
    kind: StoreKind,
    *,
    require_fast: bool,
) -> Path | None:
    suffixes = ("fast.nc",) if require_fast else ("grib2", "fast.nc")
    for suffix in suffixes:
        matches = sorted(
            directory.glob(
                f"{prefix}forecast_{kind}_144h_*hourly.{suffix}"
            )
        )
        if matches:
            return matches[0]
    return None


def native_step_hours(model: str) -> list[int]:
    cadence = 6 if model.casefold() == "aifs" else 3
    return list(range(0, 144 + 1, cadence))


def _dataset_metadata(path: Path) -> dict[str, Any] | None:
    """Open a NetCDF store and return cheap metadata, or None when invalid."""
    from netCDF4 import Dataset

    try:
        with Dataset(path, "r") as store:
            if store.getncattr("store_format") != "meteostation-point-v1":
                return None
            kind = str(store.getncattr("kind"))
            variables = {
                str(name)
                for name in store.variables
                if name not in {"step", "latitude", "longitude", "isobaricInhPa"}
            }
            steps = sorted(
                int(round(float(value)))
                for value in store.variables["step"][:]
            )
            latitudes = store.variables["latitude"][:]
            longitudes = store.variables["longitude"][:]
            levels: list[int] = []
            if "isobaricInhPa" in store.variables:
                levels = sorted(
                    int(round(float(value)))
                    for value in store.variables["isobaricInhPa"][:]
                )
            return {
                "kind": kind,
                "variables": variables,
                "steps": steps,
                "levels": levels,
                "latitude_count": int(latitudes.size),
                "longitude_count": int(longitudes.size),
                "latitude_start": float(latitudes[0]),
                "latitude_end": float(latitudes[-1]),
                "longitude_start": float(longitudes[0]),
                "longitude_end": float(longitudes[-1]),
            }
    except (OSError, RuntimeError, ValueError, IndexError):
        return None


def validate_cycle_files(
    cache_root: Path,
    model: str,
    initialized_at: datetime,
    *,
    require_fast: bool = True,
) -> dict[str, object]:
    """Deep-validate one cycle against the filesystem.

    Returns ``{"ok": bool, "checks": {...}, "errors": [...]}``.  A cycle is
    only publishable when both stores exist, open cleanly, carry the full
    variable set, every native forecast step, every native pressure level,
    and the expected global 0.25-degree grid.
    """
    directory = cycle_directory(cache_root, model, initialized_at)
    prefix = cycle_file_prefix(model, initialized_at)
    errors: list[str] = []
    checks: dict[str, object] = {}

    expected_names = (
        AIFS_PRESSURE_STORE_NAMES
        if model.casefold() == "aifs"
        else IFS_PRESSURE_STORE_NAMES
    )
    for kind in ("surface", "pressure"):
        path = _locate_store(directory, prefix, kind, require_fast=require_fast)
        if path is None:
            errors.append(f"{kind} store missing")
            checks[kind] = {"ok": False, "reason": "missing"}
            continue
        metadata = _dataset_metadata(path)
        if metadata is None:
            errors.append(f"{kind} store unreadable or incompatible")
            checks[kind] = {
                "ok": False,
                "reason": "unreadable",
                "path": str(path),
            }
            continue
        check: dict[str, object] = {
            "ok": True,
            "path": str(path),
            "metadata": metadata,
        }
        if metadata["kind"] != kind:
            errors.append(f"{kind} store has kind={metadata['kind']}")
            check["ok"] = False
        expected = (
            SURFACE_STORE_NAMES if kind == "surface" else expected_names
        )
        missing_vars = sorted(set(expected) - metadata["variables"])
        if missing_vars:
            errors.append(f"{kind} missing variables: {missing_vars}")
            check["ok"] = False
        missing_steps = sorted(set(native_step_hours(model)) - set(metadata["steps"]))
        if missing_steps:
            errors.append(f"{kind} missing steps: {missing_steps}")
            check["ok"] = False
        if kind == "pressure":
            missing_levels = sorted(
                set(FORECAST_PRESSURE_LEVELS) - set(metadata["levels"])
            )
            if missing_levels:
                errors.append(f"pressure missing levels: {missing_levels}")
                check["ok"] = False
        if metadata["latitude_count"] != EXPECTED_LATITUDE_COUNT:
            errors.append(
                f"{kind} latitude count {metadata['latitude_count']} "
                f"!= {EXPECTED_LATITUDE_COUNT}"
            )
            check["ok"] = False
        if metadata["longitude_count"] != EXPECTED_LONGITUDE_COUNT:
            errors.append(
                f"{kind} longitude count {metadata['longitude_count']} "
                f"!= {EXPECTED_LONGITUDE_COUNT}"
            )
            check["ok"] = False
        checks[kind] = check

    return {"ok": not errors, "checks": checks, "errors": errors}


@dataclass(frozen=True)
class CycleEntry:
    initialized_at: datetime
    validated_at: datetime
    surface_path: str
    pressure_path: str
    surface_bytes: int
    pressure_bytes: int

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "CycleEntry | None":
        try:
            return cls(
                initialized_at=_normalize_utc(
                    datetime.fromisoformat(str(payload["initialized_at"]))
                ),
                validated_at=_normalize_utc(
                    datetime.fromisoformat(str(payload["validated_at"]))
                ),
                surface_path=str(payload["surface_path"]),
                pressure_path=str(payload["pressure_path"]),
                surface_bytes=int(payload["surface_bytes"]),
                pressure_bytes=int(payload["pressure_bytes"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def to_json(self) -> dict[str, object]:
        return {
            "initialized_at": self.initialized_at.isoformat(),
            "validated_at": self.validated_at.isoformat(),
            "surface_path": self.surface_path,
            "pressure_path": self.pressure_path,
            "surface_bytes": self.surface_bytes,
            "pressure_bytes": self.pressure_bytes,
        }

    def age_hours(self, now: datetime | None = None) -> float:
        reference = _normalize_utc(now or datetime.now(timezone.utc))
        return max(
            0.0,
            (reference - self.initialized_at).total_seconds() / 3600.0,
        )

    def path_for(self, kind: StoreKind) -> Path:
        return Path(self.pressure_path if kind == "pressure" else self.surface_path)


def build_cycle_entry(
    cache_root: Path,
    model: str,
    initialized_at: datetime,
    *,
    require_fast: bool = True,
) -> CycleEntry | None:
    """Build a publishable manifest entry for an existing validated cycle.

    Returns ``None`` when the cycle does not pass full validation, so the
    manifest can be bootstrapped from disk without trusting any state JSON.
    """
    directory = cycle_directory(cache_root, model, initialized_at)
    prefix = cycle_file_prefix(model, initialized_at)
    surface = _locate_store(directory, prefix, "surface", require_fast=require_fast)
    pressure = _locate_store(directory, prefix, "pressure", require_fast=require_fast)
    if surface is None or pressure is None:
        return None
    report = validate_cycle_files(
        cache_root,
        model,
        initialized_at,
        require_fast=require_fast,
    )
    if not report["ok"]:
        return None
    return CycleEntry(
        initialized_at=initialized_at,
        validated_at=_normalize_utc(datetime.now(timezone.utc)),
        surface_path=surface.relative_to(Path(cache_root)).as_posix(),
        pressure_path=pressure.relative_to(Path(cache_root)).as_posix(),
        surface_bytes=surface.stat().st_size,
        pressure_bytes=pressure.stat().st_size,
    )


@dataclass
class ForecastManifest:
    """Reader/writer for ``data/state/manifest/current.json``."""

    path: Path
    cache_root: Path
    retire_grace_hours: float = 24.0
    _state: dict[str, object] | None = field(default=None, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _mtime: float | None = field(default=None, repr=False)

    # ------------------------------------------------------------------ read
    def load(self) -> dict[str, object]:
        with self._lock:
            try:
                mtime = self.path.stat().st_mtime
            except OSError:
                mtime = None
            if (
                self._state is not None
                and mtime is not None
                and mtime == self._mtime
            ):
                return self._state
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            self._state = payload
            self._mtime = mtime
            return self._state

    def cycles(self) -> dict[str, dict[str, CycleEntry | None]]:
        """Return ``{model: {"current": entry|None, "previous": entry|None}}``.

        Relative store paths are resolved against ``cache_root`` so callers
        can always open the files regardless of their working directory.
        """
        payload = self.load()
        raw = payload.get("cycles", {})
        result: dict[str, dict[str, CycleEntry | None]] = {}
        if not isinstance(raw, dict):
            return result
        for model, slots in raw.items():
            if not isinstance(slots, dict):
                continue
            parsed: dict[str, CycleEntry | None] = {
                "current": None,
                "previous": None,
            }
            for slot in ("current", "previous"):
                value = slots.get(slot)
                entry = (
                    CycleEntry.from_json(value) if isinstance(value, dict) else None
                )
                if entry is not None:
                    surface = Path(entry.surface_path)
                    pressure = Path(entry.pressure_path)
                    if not surface.is_absolute():
                        surface = self.cache_root / surface
                    if not pressure.is_absolute():
                        pressure = self.cache_root / pressure
                    entry = dataclasses.replace(
                        entry,
                        surface_path=surface.as_posix(),
                        pressure_path=pressure.as_posix(),
                    )
                parsed[slot] = entry
            result[model] = parsed
        return result

    # ----------------------------------------------------------------- write
    def publish(
        self,
        model: str,
        entry: CycleEntry,
    ) -> dict[str, object]:
        """Shift current → previous and publish *entry* as current."""
        with self._lock:
            payload = self.load()
            raw_cycles = payload.get("cycles", {})
            cycles = dict(raw_cycles) if isinstance(raw_cycles, dict) else {}
            slots = cycles.get(model, {})
            slots = dict(slots) if isinstance(slots, dict) else {}
            previous = slots.get("current")
            slots["previous"] = previous
            slots["current"] = entry.to_json()
            cycles[model] = slots
            payload = {
                **payload,
                "version": _MANIFEST_SCHEMA_VERSION,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "cycles": cycles,
            }
            _write_json_atomic(self.path, payload)
            self._state = payload
            try:
                self._mtime = self.path.stat().st_mtime
            except OSError:
                self._mtime = None
            return payload

    def set_slots(
        self,
        model: str,
        current: CycleEntry | None,
        previous: CycleEntry | None,
    ) -> dict[str, object]:
        """Atomically replace both slots of one model (order-independent)."""
        with self._lock:
            payload = self.load()
            raw_cycles = payload.get("cycles", {})
            cycles = dict(raw_cycles) if isinstance(raw_cycles, dict) else {}
            cycles[model] = {
                "current": current.to_json() if current is not None else None,
                "previous": previous.to_json() if previous is not None else None,
            }
            payload = {
                **payload,
                "version": _MANIFEST_SCHEMA_VERSION,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "cycles": cycles,
            }
            _write_json_atomic(self.path, payload)
            self._state = payload
            try:
                self._mtime = self.path.stat().st_mtime
            except OSError:
                self._mtime = None
            return payload

    def mark_retired(
        self,
        cycle_keys: dict[str, str],
    ) -> dict[str, object]:
        """Record retirement timestamps so cleanup stays delayed and traceable."""
        with self._lock:
            payload = self.load()
            retired = payload.get("retired", {})
            retired = dict(retired) if isinstance(retired, dict) else {}
            now = datetime.now(timezone.utc)
            for key, path in cycle_keys.items():
                retired[key] = {
                    "path": path,
                    "retire_at": (now + timedelta(hours=self.retire_grace_hours)).isoformat(),
                }
            payload = {
                **payload,
                "version": _MANIFEST_SCHEMA_VERSION,
                "updated_at": now.isoformat(),
                "retired": retired,
            }
            _write_json_atomic(self.path, payload)
            self._state = payload
            try:
                self._mtime = self.path.stat().st_mtime
            except OSError:
                self._mtime = None
            return payload

    def due_retired_paths(self, now: datetime | None = None) -> list[Path]:
        """Absolute paths of retired cycles whose grace period has expired."""
        payload = self.load()
        retired = payload.get("retired", {})
        if not isinstance(retired, dict):
            return []
        reference = _normalize_utc(now or datetime.now(timezone.utc))
        due: list[Path] = []
        for value in retired.values():
            if not isinstance(value, dict):
                continue
            try:
                retire_at = _normalize_utc(
                    datetime.fromisoformat(str(value["retire_at"]))
                )
            except (KeyError, ValueError):
                continue
            if retire_at <= reference:
                path = Path(str(value["path"]))
                if path.is_absolute():
                    due.append(path)
                else:
                    due.append(self.cache_root / path)
        return due


# ------------------------------------------------------------------- leases
def _lease_lock_path(cache_root: Path, model: str, initialized_at: datetime) -> Path:
    return (
        Path(cache_root)
        / "ecmwf_forecast"
        / ".leases"
        / f"{model}_{initialized_at:%Y%m%d%H}.lock"
    )


class CycleLease:
    """Advisory cross-process lease over one forecast cycle directory.

    Readers (web) take a shared lease for the duration of a request; the
    collector takes an exclusive, non-blocking lease before pruning.  On
    POSIX this maps to ``flock`` so leases are released even when a process
    crashes.  On platforms without ``flock`` the lease degrades to a no-op
    (development only).
    """

    def __init__(
        self,
        cache_root: Path,
        model: str,
        initialized_at: datetime,
        *,
        exclusive: bool = False,
        blocking: bool = True,
    ) -> None:
        self._path = _lease_lock_path(cache_root, model, initialized_at)
        self._exclusive = exclusive
        self._blocking = blocking
        self._file: Any = None
        self._held = False

    def __enter__(self) -> "CycleLease":
        if not _POSIX_FLOCK:  # pragma: no cover - development fallback
            self._held = True
            return self
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._file = open(self._path, "a+")
            operation = fcntl.LOCK_EX if self._exclusive else fcntl.LOCK_SH
            if not self._blocking:
                operation |= fcntl.LOCK_NB
            fcntl.flock(self._file.fileno(), operation)
            self._held = True
        except OSError as exc:
            if self._file is not None:
                self._file.close()
                self._file = None
            raise LeaseUnavailable(self._path) from exc
        return self

    def __exit__(self, *_: object) -> None:
        if not self._held:
            return
        if _POSIX_FLOCK and self._file is not None:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            self._file.close()
        self._file = None
        self._held = False

    @property
    def held(self) -> bool:
        return self._held


class LeaseUnavailable(Exception):
    """Raised when a non-blocking exclusive lease cannot be acquired."""
