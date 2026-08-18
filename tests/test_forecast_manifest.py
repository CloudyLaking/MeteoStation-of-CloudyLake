"""Manifest, lease, pruning and forecast API contract tests (P0)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from meteostation.forecast import manifest as manifest_module
from meteostation.forecast.collector import (
    prune_forecast_cycles,
    recent_forecast_cycles,
)
from meteostation.forecast.manifest import (
    CycleEntry,
    CycleLease,
    ForecastManifest,
    LeaseUnavailable,
    validate_cycle_files,
)


def _write_store(path: Path, *, kind: str, steps: list[int], levels: list[int] | None) -> None:
    from netCDF4 import Dataset

    path.parent.mkdir(parents=True, exist_ok=True)
    latitudes = np.linspace(90.0, -90.0, 2, dtype=np.float32)
    longitudes = np.linspace(0.0, 359.5, 2, dtype=np.float32)
    with Dataset(path, "w", format="NETCDF4") as store:
        store.setncattr("store_format", "meteostation-point-v1")
        store.setncattr("kind", kind)
        store.createDimension("step", len(steps))
        store.createDimension("latitude", len(latitudes))
        store.createDimension("longitude", len(longitudes))
        store.createVariable("step", "i2", ("step",))[:] = steps
        store.createVariable("latitude", "f4", ("latitude",))[:] = latitudes
        store.createVariable("longitude", "f4", ("longitude",))[:] = longitudes
        if levels:
            store.createDimension("isobaricInhPa", len(levels))
            store.createVariable("isobaricInhPa", "f4", ("isobaricInhPa",))[:] = levels
        names = (
            ["u10", "v10", "t2m", "d2m", "sp", "msl", "tp", "tcc"]
            if kind == "surface"
            else ["gh", "t", "r", "u", "v"]
        )
        shape = (len(steps), len(levels), len(latitudes), len(longitudes)) if levels else (len(steps), len(latitudes), len(longitudes))
        dimensions = ("step", "isobaricInhPa", "latitude", "longitude") if levels else ("step", "latitude", "longitude")
        for name in names:
            store.createVariable(name, "f4", dimensions)[:] = np.zeros(shape, dtype=np.float32)


def _cycle_files(
    root: Path,
    model: str,
    initialized_at: datetime,
    *,
    steps: list[int] | None = None,
    levels: list[int] | None = None,
    surface_ok: bool = True,
) -> Path:
    directory = (
        root / "ecmwf_forecast" / model / f"{initialized_at:%Y}"
        / f"{initialized_at:%m}" / f"{initialized_at:%d}"
    )
    prefix = f"{model}_{initialized_at:%Y%m%d}_{initialized_at:%H}z_"
    cadence = 6 if model == "aifs" else 3
    steps = steps or list(range(0, 145, cadence))
    if surface_ok:
        _write_store(
            directory / f"{prefix}forecast_surface_144h_{cadence}hourly.fast.nc",
            kind="surface",
            steps=steps,
            levels=None,
        )
    _write_store(
        directory / f"{prefix}forecast_pressure_144h_{cadence}hourly.fast.nc",
        kind="pressure",
        steps=steps,
        levels=levels or [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50, 10],
    )
    return directory


def test_manifest_publish_shifts_current_to_previous(tmp_path: Path) -> None:
    manifest = ForecastManifest(tmp_path / "state" / "manifest" / "current.json", tmp_path)
    first = CycleEntry(
        initialized_at=datetime(2026, 8, 17, 12, tzinfo=timezone.utc),
        validated_at=datetime(2026, 8, 17, 18, tzinfo=timezone.utc),
        surface_path="ecmwf_forecast/ifs/2026/08/17/ifs_20260817_12z_forecast_surface_144h_3hourly.fast.nc",
        pressure_path="ecmwf_forecast/ifs/2026/08/17/ifs_20260817_12z_forecast_pressure_144h_3hourly.fast.nc",
        surface_bytes=100,
        pressure_bytes=200,
    )
    second = CycleEntry(
        initialized_at=datetime(2026, 8, 17, 18, tzinfo=timezone.utc),
        validated_at=datetime(2026, 8, 18, 0, tzinfo=timezone.utc),
        surface_path="ecmwf_forecast/ifs/2026/08/17/ifs_20260817_18z_forecast_surface_144h_3hourly.fast.nc",
        pressure_path="ecmwf_forecast/ifs/2026/08/17/ifs_20260817_18z_forecast_pressure_144h_3hourly.fast.nc",
        surface_bytes=300,
        pressure_bytes=400,
    )
    manifest.publish("ifs", first)
    manifest.publish("ifs", second)
    slots = manifest.cycles()["ifs"]
    assert slots["current"].initialized_at == second.initialized_at
    assert slots["previous"].initialized_at == first.initialized_at
    # Paths are absolutized against the cache root.
    assert Path(slots["current"].surface_path).is_absolute()


def test_manifest_load_is_atomic_and_fresh(tmp_path: Path) -> None:
    path = tmp_path / "manifest" / "current.json"
    manifest = ForecastManifest(path, tmp_path)
    assert manifest.load() == {}
    entry = CycleEntry(
        initialized_at=datetime(2026, 8, 17, 18, tzinfo=timezone.utc),
        validated_at=datetime(2026, 8, 18, 0, tzinfo=timezone.utc),
        surface_path="s.fast.nc",
        pressure_path="p.fast.nc",
        surface_bytes=1,
        pressure_bytes=2,
    )
    manifest.publish("aifs", entry)
    reloaded = ForecastManifest(path, tmp_path)
    assert reloaded.cycles()["aifs"]["current"].initialized_at == entry.initialized_at


def test_validate_cycle_files_rejects_missing_variables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manifest_module, "EXPECTED_LATITUDE_COUNT", 2)
    monkeypatch.setattr(manifest_module, "EXPECTED_LONGITUDE_COUNT", 2)
    root = tmp_path
    initialized_at = datetime(2026, 8, 17, 18, tzinfo=timezone.utc)
    directory = _cycle_files(root, "ifs", initialized_at)
    # All variables present: the cycle validates (grid patched to 2x2).
    report = validate_cycle_files(root, "ifs", initialized_at)
    assert report["ok"] is True, report["errors"]
    # Now remove the surface file entirely.
    surface = next(directory.glob("*_surface_*.fast.nc"))
    surface.unlink()
    report = validate_cycle_files(root, "ifs", initialized_at)
    assert report["ok"] is False
    assert any("surface store missing" in error for error in report["errors"])


def test_validate_cycle_files_requires_full_steps_and_levels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manifest_module, "EXPECTED_LATITUDE_COUNT", 2)
    monkeypatch.setattr(manifest_module, "EXPECTED_LONGITUDE_COUNT", 2)
    root = tmp_path
    initialized_at = datetime(2026, 8, 17, 18, tzinfo=timezone.utc)
    _cycle_files(
        root,
        "ifs",
        initialized_at,
        steps=[0, 3],
        levels=[1000, 500],
    )
    report = validate_cycle_files(root, "ifs", initialized_at)
    assert report["ok"] is False
    errors = "; ".join(str(error) for error in report["errors"])
    assert "missing steps" in errors
    assert "missing levels" in errors


def test_validate_cycle_files_accepts_complete_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manifest_module, "EXPECTED_LATITUDE_COUNT", 2)
    monkeypatch.setattr(manifest_module, "EXPECTED_LONGITUDE_COUNT", 2)
    root = tmp_path
    initialized_at = datetime(2026, 8, 17, 18, tzinfo=timezone.utc)
    _cycle_files(root, "ifs", initialized_at)
    report = validate_cycle_files(root, "ifs", initialized_at)
    assert report["ok"] is True, report["errors"]


def test_prune_forecast_cycles_respects_protected(tmp_path: Path) -> None:
    root = tmp_path
    old = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)
    new = datetime(2026, 8, 17, 18, tzinfo=timezone.utc)
    _cycle_files(root, "ifs", old)
    _cycle_files(root, "ifs", new)
    removed = prune_forecast_cycles(
        root / "ecmwf_forecast" / "ifs",
        keep=1,
        protected={old},
    )
    assert removed == [new.isoformat()] or removed == []
    old_dir = root / "ecmwf_forecast" / "ifs" / "2026" / "08" / "16"
    assert any(old_dir.rglob("*surface*.fast.nc"))


def test_prune_forecast_cycles_marks_retired_with_manifest(tmp_path: Path) -> None:
    root = tmp_path
    manifest = ForecastManifest(tmp_path / "state" / "manifest" / "current.json", tmp_path)
    old = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)
    new = datetime(2026, 8, 17, 18, tzinfo=timezone.utc)
    _cycle_files(root, "ifs", old)
    _cycle_files(root, "ifs", new)
    removed = prune_forecast_cycles(
        root / "ecmwf_forecast" / "ifs",
        keep=1,
        protected=set(),
        manifest=manifest,
    )
    # Files must still exist (delayed cleanup).
    old_dir = root / "ecmwf_forecast" / "ifs" / "2026" / "08" / "16"
    assert any(old_dir.rglob("*surface*.fast.nc"))
    payload = manifest.load()
    retired = payload.get("retired", {})
    assert retired
    assert any("retire_at" in value for value in retired.values())
    assert removed == [old.isoformat()]


def test_retire_after_grace_deletes_files(tmp_path: Path) -> None:
    root = tmp_path
    manifest = ForecastManifest(tmp_path / "state" / "manifest" / "current.json", tmp_path)
    old = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)
    old_dir = _cycle_files(root, "ifs", old)
    from meteostation.forecast.collector import ForecastCollector, ForecastCollectorConfig

    collector = ForecastCollector(
        config=ForecastCollectorConfig(
            retain_complete_cycles=2,
            retire_grace_hours=1,
            models=["ifs"],
            cycles=["00", "06", "12", "18"],
        ),
        cache_root=root,
        state_path=tmp_path / "state" / "forecast_collector.json",
        manifest_path=tmp_path / "state" / "manifest" / "current.json",
    )
    collector.manifest.mark_retired(
        {
            "ifs|2026-08-16T12:00:00+00:00": sorted(
                old_dir.glob("*.fast.nc")
            )[0].relative_to(root).as_posix()
        }
    )
    # Force the retire_at into the past.
    payload = collector.manifest.load()
    for value in payload["retired"].values():
        value["retire_at"] = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
    collector.manifest.path.write_text(
        json.dumps(payload), encoding="utf-8"
    )
    collector.manifest._state = None
    removed = collector._retire_due_cycles("ifs")
    assert removed
    assert not any(old_dir.rglob("*.fast.nc"))


@pytest.mark.skipif(
    not manifest_module._POSIX_FLOCK,
    reason="flock leases require POSIX",
)
def test_cycle_lease_shared_blocks_exclusive(tmp_path: Path) -> None:
    initialized_at = datetime(2026, 8, 17, 18, tzinfo=timezone.utc)
    shared = CycleLease(tmp_path, "ifs", initialized_at, exclusive=False)
    with shared:
        with pytest.raises(LeaseUnavailable):
            CycleLease(
                tmp_path,
                "ifs",
                initialized_at,
                exclusive=True,
                blocking=False,
            ).__enter__()


def test_recent_forecast_cycles_returns_newest_first() -> None:
    reference = datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc)
    cycles = recent_forecast_cycles(
        reference_time=reference,
        cycles=["00", "06", "12", "18"],
        count=4,
    )
    assert cycles[0] == datetime(2026, 8, 18, 6, tzinfo=timezone.utc)
    assert cycles[-1] == datetime(2026, 8, 17, 12, tzinfo=timezone.utc)
    assert all(cycles[i] > cycles[i + 1] for i in range(len(cycles) - 1))
