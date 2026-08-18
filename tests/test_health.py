"""Health endpoints, data-health aggregation and page-view dedup tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meteostation.health import (
    HealthMetrics,
    collect_data_health,
    forecast_manifest_health,
    looks_like_bot,
)
from meteostation.operations import RuntimeTraffic
from web import app as web_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(web_app.app, raise_server_exceptions=False)


def _fresh_manifest() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {
        "cycles": {
            "ifs": {
                "current": {
                    "initialized_at": (now - timedelta(hours=3)).isoformat(),
                    "surface_path": "s.fast.nc",
                    "pressure_path": "p.fast.nc",
                    "surface_bytes": 1,
                    "pressure_bytes": 2,
                },
                "previous": None,
            },
            "aifs": {
                "current": {
                    "initialized_at": (now - timedelta(hours=6)).isoformat(),
                    "surface_path": "s.fast.nc",
                    "pressure_path": "p.fast.nc",
                    "surface_bytes": 1,
                    "pressure_bytes": 2,
                },
                "previous": None,
            },
        }
    }


def test_forecast_manifest_health_stale_after_threshold() -> None:
    now = datetime.now(timezone.utc)
    manifest = {
        "cycles": {
            "ifs": {
                "current": {
                    "initialized_at": (now - timedelta(hours=20)).isoformat(),
                    "surface_path": "s",
                    "pressure_path": "p",
                    "surface_bytes": 1,
                    "pressure_bytes": 2,
                },
                "previous": None,
            }
        }
    }
    report = forecast_manifest_health(
        manifest,
        max_stale_hours={"ifs": 18.0, "aifs": 30.0},
        now=now,
    )
    assert report["ifs"]["stale"] is True
    assert report["ifs"]["age_hours"] == pytest.approx(20.0, abs=0.1)


def test_collect_data_health_stale_without_products(tmp_path: Path) -> None:
    metrics = HealthMetrics(tmp_path / "health.json")
    now = datetime.now(timezone.utc)
    report = collect_data_health(
        project_root=tmp_path,
        metrics=metrics,
        max_stale_hours={"ifs": 18.0, "aifs": 30.0},
        manifest_payload={},
        now=now,
    )
    assert report["status"] == "stale"
    assert report["forecast"]["ifs"]["available"] is False
    assert report["weather_maps"]["ok"] is False
    assert "disk" in report


def test_collect_data_health_ok_with_fresh_products(tmp_path: Path) -> None:
    metrics = HealthMetrics(tmp_path / "health.json")
    now = datetime.now(timezone.utc)
    report = collect_data_health(
        project_root=tmp_path,
        metrics=metrics,
        max_stale_hours={"ifs": 18.0, "aifs": 30.0},
        manifest_payload=_fresh_manifest(),
        weather_map_meta={
            "latest_valid_at": (now - timedelta(hours=6)).isoformat(),
            "publication_status": "development-preview",
        },
        now=now,
    )
    assert report["status"] == "ok"
    assert report["weather_maps"]["ok"] is True
    assert report["forecast"]["ifs"]["stale"] is False


def test_page_views_are_deduplicated_per_session_and_day(
    tmp_path: Path,
) -> None:
    traffic = RuntimeTraffic(tmp_path / "traffic.json")
    assert traffic.snapshot()["monthly_page_views"] == 0
    traffic.record_page_view("session-a", "/")
    traffic.record_page_view("session-a", "/")
    traffic.record_page_view("session-a", "/forecast")
    traffic.record_page_view("session-b", "/")
    assert traffic.snapshot()["monthly_page_views"] == 3


def test_page_views_exclude_bots_and_unknown_paths(
    client: TestClient,
) -> None:
    response = client.get("/error.php")
    assert response.status_code == 404
    response = client.get("/", headers={"user-agent": "curl/8.0"})
    assert response.status_code == 200
    response = client.get("/robots.txt")
    assert response.status_code == 404


def test_looks_like_bot_patterns() -> None:
    assert looks_like_bot("Mozilla/5.0 (compatible; Googlebot/2.1)")
    assert looks_like_bot("curl/7.68.0")
    assert looks_like_bot(None) is False
    assert looks_like_bot("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126") is False


def test_health_live_and_data(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"
    response = client.get("/health/data")
    assert response.status_code == 200
    payload = response.json()
    for key in ("forecast", "weather_maps", "wis2", "qweather", "disk", "status"):
        assert key in payload


def test_health_ready_fails_when_data_stale(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _stale_report() -> dict[str, object]:
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "status": "stale",
            "forecast": {
                "ifs": {"available": False, "stale": True},
                "aifs": {"available": False, "stale": True},
            },
            "weather_maps": {"ok": False, "latest_valid_at": None},
        }

    monkeypatch.setattr(web_app, "_health_data_report", _stale_report)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_health_ready_ok_when_fresh(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fresh_report() -> dict[str, object]:
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok",
            "forecast": {},
            "weather_maps": {},
        }

    monkeypatch.setattr(web_app, "_health_data_report", _fresh_report)
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_metrics_endpoint_shape(client: TestClient) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    payload = response.json()
    for key in ("traffic", "latency", "qweather", "tasks", "disk", "forecast"):
        assert key in payload


def test_qweather_metrics_recorded(tmp_path: Path) -> None:
    metrics = HealthMetrics(tmp_path / "health.json")
    metrics.record_qweather(True, 123.4)
    metrics.record_qweather(False, 500.0)
    snapshot = metrics.snapshot()["qweather"]
    assert snapshot["total"] == 2
    assert snapshot["success"] == 1
    assert snapshot["last_latency_ms"] == 500.0
    assert snapshot["consecutive_failures"] == 1


def test_task_metrics_recorded(tmp_path: Path) -> None:
    metrics = HealthMetrics(tmp_path / "health.json")
    metrics.record_task("reanalysis", True)
    metrics.record_task("reanalysis", False)
    snapshot = metrics.snapshot()["tasks"]
    assert snapshot["reanalysis"]["success"] == 1
    assert snapshot["reanalysis"]["failure"] == 1
    assert snapshot["reanalysis"]["consecutive_failures"] == 1


def test_health_state_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    metrics = HealthMetrics(path)
    metrics.record_qweather(True, 10.0)
    reloaded = HealthMetrics(path)
    assert reloaded.snapshot()["qweather"]["success"] == 1
