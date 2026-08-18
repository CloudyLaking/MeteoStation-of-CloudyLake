"""Health and monitoring collection for CloudyLake's Observatory.

Splits the public checks into three layers:

- ``/health/live``   — the web process is alive;
- ``/health/ready``  — core dependencies and the current products are usable
  (fails when forecast or weather-map data is missing or over age);
- ``/health/data``   — per-source freshness report, always HTTP 200.

``/metrics`` exposes internal monitoring values (no secrets).  Runtime
counters persist to ``data/state/health.json``; latency percentiles are kept
in bounded in-memory rings.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

_BOT_USER_AGENT_PATTERN = re.compile(
    r"(?i)bot|crawler|spider|scrape|curl|wget|python-requests|"
    r"httpx|okhttp|java/|go-http-client|libwww|facebookexternalhit|"
    r"semrush|ahrefs|mj12|baiduspider|sogou|yandex|bingpreview|headlesschrome|"
    r"monitor|uptime|healthcheck|pingdom"
)

# Request paths that count as real public pages.  Everything else is api,
# static, or an unknown/bot probe and never becomes a page view.
PAGE_PATHS = frozenset(
    {
        "/",
        "/observations",
        "/forecast",
        "/sounding-forecast",
        "/reanalysis",
        "/about",
        "/colorbar-translator",
        "/admin",
    }
)


def looks_like_bot(user_agent: str | None) -> bool:
    return bool(user_agent) and _BOT_USER_AGENT_PATTERN.search(user_agent) is not None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HealthMetrics:
    """Persistent success/failure counters plus bounded latency rings."""

    def __init__(self, state_path: Path) -> None:
        self.state_path = Path(state_path)
        self._lock = threading.Lock()
        self._api_latencies: deque[float] = deque(maxlen=512)
        self._page_latencies: deque[float] = deque(maxlen=256)
        self._state = self._load()

    def _load(self) -> dict[str, object]:
        default: dict[str, object] = {
            "started_at": _now_iso(),
            "qweather": {
                "total": 0,
                "success": 0,
                "last_success_at": None,
                "last_latency_ms": None,
                "consecutive_failures": 0,
            },
            "tasks": {},
        }
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return default
        if not isinstance(loaded, dict):
            return default
        return {**default, **loaded}

    # ------------------------------------------------------------- recording
    def record_qweather(self, ok: bool, latency_ms: float) -> None:
        with self._lock:
            entry = dict(self._state.get("qweather", {}))
            entry["total"] = int(entry.get("total", 0)) + 1
            entry["last_latency_ms"] = round(float(latency_ms), 1)
            if ok:
                entry["success"] = int(entry.get("success", 0)) + 1
                entry["last_success_at"] = _now_iso()
                entry["consecutive_failures"] = 0
            else:
                entry["consecutive_failures"] = (
                    int(entry.get("consecutive_failures", 0)) + 1
                )
            self._state["qweather"] = entry
            self._flush_locked()

    def record_task(self, name: str, ok: bool) -> None:
        with self._lock:
            tasks = dict(self._state.get("tasks", {}))
            entry = dict(tasks.get(name, {}))
            entry["last_run_at"] = _now_iso()
            if ok:
                entry["success"] = int(entry.get("success", 0)) + 1
                entry["consecutive_failures"] = 0
            else:
                entry["failure"] = int(entry.get("failure", 0)) + 1
                entry["consecutive_failures"] = (
                    int(entry.get("consecutive_failures", 0)) + 1
                )
            tasks[name] = entry
            self._state["tasks"] = tasks
            self._flush_locked()

    def record_api_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._api_latencies.append(float(latency_ms))

    def record_page_latency(self, latency_ms: float) -> None:
        with self._lock:
            self._page_latencies.append(float(latency_ms))

    # -------------------------------------------------------------- snapshot
    def snapshot(self) -> dict[str, object]:
        with self._lock:
            state = {
                key: (
                    dict(value) if isinstance(value, dict) else value
                )
                for key, value in self._state.items()
            }
            api = sorted(self._api_latencies)
            pages = sorted(self._page_latencies)
            state["api_latency_ms"] = {
                "count": len(api),
                "p50": _percentile(api, 0.50),
                "p95": _percentile(api, 0.95),
                "max": api[-1] if api else None,
            }
            state["page_latency_ms"] = {
                "count": len(pages),
                "p50": _percentile(pages, 0.50),
                "p95": _percentile(pages, 0.95),
                "max": pages[-1] if pages else None,
            }
            return state

    def _flush_locked(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)


def _percentile(sorted_values: list[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, int(round(fraction * (len(sorted_values) - 1))))
    return round(sorted_values[index], 1)


def read_json_optional(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _age_hours(value: str | None, now: datetime) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds() / 3600.0)


def forecast_manifest_health(
    manifest_payload: dict[str, object],
    *,
    max_stale_hours: dict[str, float],
    now: datetime | None = None,
) -> dict[str, object]:
    """Freshness of IFS/AIFS current cycles from the manifest payload."""
    now = now or datetime.now(timezone.utc)
    report: dict[str, object] = {}
    for model in ("ifs", "aifs"):
        entry: dict[str, object] = {"available": False, "model": model}
        slots = (
            manifest_payload.get("cycles", {}).get(model, {})
            if isinstance(manifest_payload.get("cycles", {}), dict)
            else {}
        )
        if isinstance(slots, dict):
            current = slots.get("current")
            if isinstance(current, dict):
                entry["available"] = True
                entry["initialized_at"] = current.get("initialized_at")
                age = _age_hours(str(current.get("initialized_at")), now)
                entry["age_hours"] = round(age, 2) if age is not None else None
                threshold = float(max_stale_hours.get(model, 18.0))
                entry["max_stale_hours"] = threshold
                entry["stale"] = bool(
                    age is None or age > threshold
                )
                previous = slots.get("previous")
                entry["has_previous"] = isinstance(previous, dict)
        report[model] = entry
    return report


def collect_data_health(
    *,
    project_root: Path,
    metrics: HealthMetrics,
    max_stale_hours: dict[str, float],
    weather_map_meta: dict[str, object] | None = None,
    manifest_payload: dict[str, object] | None = None,
    sounding_stations_payload: dict[str, object] | None = None,
    global_sounding_payload: dict[str, object] | None = None,
    wis2_payload: dict[str, object] | None = None,
    traffic_payload: dict[str, object] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Assemble the per-source freshness report and an overall status."""
    now = now or datetime.now(timezone.utc)
    report: dict[str, object] = {"checked_at": now.isoformat()}

    # ---- forecast ----
    report["forecast"] = forecast_manifest_health(
        manifest_payload or {},
        max_stale_hours=max_stale_hours,
        now=now,
    )
    forecast_ok = any(
        isinstance(item, dict) and item.get("available") and not item.get("stale")
        for item in report["forecast"].values()
    )

    # ---- weather maps ----
    weather = dict(weather_map_meta or {})
    latest_valid_at = str(weather.get("latest_valid_at") or "")
    age = _age_hours(latest_valid_at, now)
    weather["age_hours"] = round(age, 2) if age is not None else None
    weather["max_age_hours"] = 48.0
    weather["ok"] = bool(age is not None and age <= 48.0)
    report["weather_maps"] = weather

    # ---- China soundings ----
    sounding: dict[str, object] = {"updated": None, "total": None}
    stations = sounding_stations_payload or {}
    if isinstance(stations, dict):
        by_cycle = stations.get("station_ids_by_cycle", {})
        if isinstance(by_cycle, dict) and by_cycle:
            latest_cycle = max(by_cycle.keys())
            updated = (
                len(by_cycle[latest_cycle])
                if isinstance(by_cycle[latest_cycle], (list, dict))
                else None
            )
            sounding["updated"] = updated
            sounding["cycle"] = latest_cycle
            sounding["cycle_age_hours"] = _age_hours(latest_cycle, now)
        total = stations.get("station_count")
        if total is not None:
            sounding["total"] = int(total)
    report["soundings_china"] = sounding

    # ---- Wyoming backfill ----
    global_sounding = global_sounding_payload or {}
    last_run = global_sounding.get("last_run")
    if isinstance(last_run, dict):
        report["wyoming"] = {
            "last_run_at": last_run.get("started_at"),
            "completed": last_run.get("completed"),
            "skipped": last_run.get("skipped"),
            "failed": last_run.get("failed"),
        }
    else:
        report["wyoming"] = {"last_run_at": None}

    # ---- WIS2 ----
    wis2 = wis2_payload or {}
    report["wis2"] = {
        "connected": wis2.get("connected"),
        "last_download_at": wis2.get("last_download_at"),
        "error_count": wis2.get("error_count"),
        "queued_notifications": wis2.get("queued_notifications"),
        "anomaly_count": wis2.get("anomaly_count", 0),
        "future_time_count": wis2.get("future_time_count", 0),
    }

    # ---- q-weather + tasks + latency (runtime metrics) ----
    runtime = metrics.snapshot()
    report["qweather"] = runtime.get("qweather", {})
    report["tasks"] = runtime.get("tasks", {})
    report["http"] = {
        "status_counts": (traffic_payload or {}).get("status_counts", {}),
        "api_latency_ms": runtime.get("api_latency_ms", {}),
        "page_latency_ms": runtime.get("page_latency_ms", {}),
    }

    # ---- disk ----
    state_root = project_root / "data" / "raw"
    try:
        usage = shutil.disk_usage(state_root)
        total_gb = usage.total / 1024**3
        free_gb = usage.free / 1024**3
    except OSError:
        total_gb = free_gb = 0.0
    report["disk"] = {
        "total_gb": round(total_gb, 2),
        "free_gb": round(free_gb, 2),
        "minimum_free_gb": 3.0,
        "download_reserve_gb": 3.0,
        "next_cycle_estimate_gb": 5.1,
        "ok": free_gb >= 6.0,
    }

    stale = not forecast_ok or not bool(weather["ok"])
    report["status"] = "stale" if stale else "ok"
    return report


class QWeatherObserverRegistry:
    """Tiny hook so the observation module can report outcomes decoupled."""

    def __init__(self) -> None:
        self._observers: list[Callable[[bool, float], None]] = []
        self._lock = threading.Lock()

    def register(self, observer: Callable[[bool, float], None]) -> None:
        with self._lock:
            self._observers.append(observer)

    def notify(self, ok: bool, latency_ms: float) -> None:
        with self._lock:
            observers = list(self._observers)
        for observer in observers:
            try:
                observer(ok, latency_ms)
            except Exception:
                continue


qweather_registry = QWeatherObserverRegistry()
