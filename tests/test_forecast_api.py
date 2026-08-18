"""Forecast API contract tests: 200 with degradation meta, structured 503."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meteostation.forecast.manifest import CycleEntry, ForecastManifest
from web import app as web_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(web_app.app, raise_server_exceptions=False)


def _point() -> dict[str, object]:
    return {
        "id": "58362",
        "name": "SHANGHAI (BAOSHAN)",
        "latitude": 31.4,
        "longitude": 121.45,
    }


def test_surface_forecast_returns_200_with_degradation_meta(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from meteostation.forecast.models import (
        SurfaceForecast,
        SurfaceForecastPoint,
    )

    initialized_at = datetime(2026, 8, 17, 18, tzinfo=timezone.utc)
    fake_path = Path("surface.fast.nc")
    monkeypatch.setattr(web_app, "resolve_forecast_location", lambda _: _point())

    def _fail(*args, **kwargs):
        raise FileNotFoundError("not cached")

    monkeypatch.setattr(web_app, "retrieve_ecmwf_forecast", _fail)
    monkeypatch.setattr(
        web_app,
        "_resolve_forecast_cycle",
        lambda model, field_type, requested_at=None, reference=None: (
            initialized_at,
            fake_path,
            True,  # degraded: previous cycle used
            12.5,
        ),
    )
    monkeypatch.setattr(
        web_app,
        "extract_surface_forecast",
        lambda *args, **kwargs: SurfaceForecast(
            station_id="58362",
            station_name="SHANGHAI (BAOSHAN)",
            latitude=31.4,
            longitude=121.45,
            initialized_at=initialized_at,
            source="ECMWF Open Data",
            points=[
                SurfaceForecastPoint(
                    valid_at=initialized_at + timedelta(hours=3),
                    step_hours=3,
                    temperature_2m_c=28.0,
                )
            ],
        ),
    )
    response = client.get("/api/v1/forecast/surface/58362")
    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["degraded"] is True
    assert payload["meta"]["data_age_hours"] == 12.5
    assert payload["meta"]["initialized_at"] == initialized_at.isoformat()
    assert payload["meta"]["max_stale_hours"] > 0
    assert len(payload["points"]) == 1


def test_surface_forecast_returns_structured_503_when_stale(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_app, "resolve_forecast_location", lambda _: _point())

    def _fail(*args, **kwargs):
        raise FileNotFoundError("not cached")

    monkeypatch.setattr(web_app, "retrieve_ecmwf_forecast", _fail)

    def _stale(*args, **kwargs):
        raise web_app._forecast_unavailable(
            "ifs",
            reason="stale",
            age_hours=30.0,
        )

    monkeypatch.setattr(web_app, "_resolve_forecast_cycle", _stale)
    response = client.get("/api/v1/forecast/surface/58362")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["status"] == "unavailable"
    assert detail["reason"] == "stale"
    assert detail["age_hours"] == 30.0
    assert detail["max_stale_hours"] > 0


def test_forecast_extract_failure_returns_503_not_500(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vanished file during extraction must surface as structured 503."""
    initialized_at = datetime(2026, 8, 17, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(web_app, "resolve_forecast_location", lambda _: _point())
    monkeypatch.setattr(
        web_app,
        "retrieve_ecmwf_forecast",
        lambda **kwargs: (Path("surface.fast.nc"), Path("pressure.fast.nc")),
    )

    def _vanish(*args, **kwargs):
        raise FileNotFoundError("file vanished")

    monkeypatch.setattr(web_app, "extract_surface_forecast", _vanish)
    response = client.get("/api/v1/forecast/surface/58362")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["status"] == "unavailable"
    assert "missing" in detail["reason"]


def test_forecast_cache_status_cross_validates_filesystem(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = ForecastManifest(tmp_path / "manifest.json", tmp_path)
    monkeypatch.setattr(web_app, "forecast_manifest", manifest)
    monkeypatch.setattr(
        web_app,
        "FORECAST_COLLECTOR_STATE_PATH",
        tmp_path / "forecast_collector.json",
    )
    # A manifest entry whose files do not exist must be reported unavailable.
    manifest.publish(
        "ifs",
        CycleEntry(
            initialized_at=datetime(2026, 8, 17, 18, tzinfo=timezone.utc),
            validated_at=datetime(2026, 8, 18, 0, tzinfo=timezone.utc),
            surface_path="missing_surface.fast.nc",
            pressure_path="missing_pressure.fast.nc",
            surface_bytes=123,
            pressure_bytes=456,
        ),
    )
    response = client.get("/api/v1/forecast/cache/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["manifest"]["ifs"]["available"] is False


def test_forecast_cache_status_manifest_available_when_files_exist(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = ForecastManifest(tmp_path / "manifest.json", tmp_path)
    monkeypatch.setattr(web_app, "forecast_manifest", manifest)
    monkeypatch.setattr(
        web_app,
        "FORECAST_COLLECTOR_STATE_PATH",
        tmp_path / "forecast_collector.json",
    )
    surface = tmp_path / "surface.fast.nc"
    pressure = tmp_path / "pressure.fast.nc"
    surface.write_bytes(b"x" * 123)
    pressure.write_bytes(b"y" * 456)
    manifest.publish(
        "aifs",
        CycleEntry(
            initialized_at=datetime(2026, 8, 17, 18, tzinfo=timezone.utc),
            validated_at=datetime(2026, 8, 18, 0, tzinfo=timezone.utc),
            surface_path=surface.name,
            pressure_path=pressure.name,
            surface_bytes=123,
            pressure_bytes=456,
        ),
    )
    response = client.get("/api/v1/forecast/cache/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["manifest"]["aifs"]["available"] is True
    assert payload["manifest"]["aifs"]["initialized_at"].startswith("2026-08-17")
    assert payload["manifest"]["aifs"]["max_stale_hours"] > 0
