"""Runtime configuration, traffic counters and operations status helpers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator


VERSION = "V2.2.1"
DEFAULT_SITE_CONFIG = {
    "version": VERSION,
    "theme": {
        "primary": "#126E68",
        "accent": "#F2C94C",
        "blue": "#2563A9",
    },
    "homepage": {
        "title": "中国天气自动分析",
        "subtitle": "探空实况、天气形势与模式背景的统一工作台",
        "station_title": "探空工作台",
        "station_subtitle": "点击地图站点或输入站号，可选择时次、图形和地面订正方式。",
    },
    "footer": {
        "copyright": "Copyright © 2026- CloudyLake. All Rights Reserved.",
        "contact": "cloudylaking@outlook.com",
        "powered_with": "Powered with Codex & Deepseek",
    },
}


class ThemeConfig(BaseModel):
    primary: str = "#126E68"
    accent: str = "#F2C94C"
    blue: str = "#2563A9"

    @field_validator("primary", "accent", "blue")
    @classmethod
    def validate_colour(cls, value: str) -> str:
        normalized = value.strip().upper()
        if (
            len(normalized) != 7
            or not normalized.startswith("#")
            or any(character not in "0123456789ABCDEF" for character in normalized[1:])
        ):
            raise ValueError("颜色必须使用 #RRGGBB 格式")
        return normalized


class HomepageConfig(BaseModel):
    title: str = Field(min_length=2, max_length=40)
    subtitle: str = Field(min_length=2, max_length=120)
    station_title: str = Field(default="探空工作台", min_length=2, max_length=40)
    station_subtitle: str = Field(
        default="点击地图站点或输入站号，可选择时次、图形和地面订正方式。",
        min_length=2,
        max_length=160,
    )


class FooterConfig(BaseModel):
    copyright: str = Field(min_length=2, max_length=120)
    contact: str = Field(min_length=3, max_length=120)
    powered_with: str = Field(min_length=2, max_length=120)

    @field_validator("copyright", "contact", "powered_with")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.strip().split())


class SiteConfig(BaseModel):
    version: str = VERSION
    theme: ThemeConfig = Field(default_factory=ThemeConfig)
    homepage: HomepageConfig = Field(
        default_factory=lambda: HomepageConfig(
            **DEFAULT_SITE_CONFIG["homepage"],
        )
    )
    footer: FooterConfig = Field(
        default_factory=lambda: FooterConfig(**DEFAULT_SITE_CONFIG["footer"])
    )


class RuntimeTraffic:
    """Small persistent counter for application traffic.

    This intentionally counts traffic handled by the application rather than
    presenting provider billing traffic as an exact figure.
    """

    def __init__(self, state_path: Path) -> None:
        self.state_path = Path(state_path)
        self._lock = threading.Lock()
        self._dirty_requests = 0
        self._last_flush = 0.0
        self._state = self._load()

    def _load(self) -> dict[str, object]:
        month_key = _current_month_key()
        default = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "requests": 0,
            "response_bytes": 0,
            "month_key": month_key,
            "monthly_page_views": 0,
            "status_counts": {},
            "path_counts": {},
            "last_request_at": None,
        }
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return default
        merged = {**default, **loaded}
        if "monthly_page_views" not in loaded:
            started_at = _parse_datetime(merged.get("started_at"))
            started_month = (
                started_at.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")
                if started_at is not None
                else None
            )
            merged["monthly_page_views"] = (
                int(dict(merged.get("path_counts", {})).get("page", 0))
                if started_month == month_key
                else 0
            )
            merged["month_key"] = month_key
        return merged

    def _roll_month_locked(self) -> None:
        current = _current_month_key()
        if self._state.get("month_key") == current:
            return
        self._state["month_key"] = current
        self._state["monthly_page_views"] = 0
        self._dirty_requests += 1

    def record(self, path: str, status_code: int, response_bytes: int) -> None:
        if path.startswith("/static/") or path.startswith("/brand/"):
            category = "static"
        elif path.startswith("/api/"):
            category = "api"
        else:
            category = "page"
        with self._lock:
            self._roll_month_locked()
            self._state["requests"] = int(self._state["requests"]) + 1
            self._state["response_bytes"] = (
                int(self._state["response_bytes"]) + max(0, response_bytes)
            )
            status_counts = dict(self._state.get("status_counts", {}))
            status_group = f"{status_code // 100}xx"
            status_counts[status_group] = int(status_counts.get(status_group, 0)) + 1
            self._state["status_counts"] = status_counts
            path_counts = dict(self._state.get("path_counts", {}))
            path_counts[category] = int(path_counts.get(category, 0)) + 1
            self._state["path_counts"] = path_counts
            if category == "page":
                self._state["monthly_page_views"] = (
                    int(self._state.get("monthly_page_views", 0)) + 1
                )
            self._state["last_request_at"] = datetime.now(timezone.utc).isoformat()
            self._dirty_requests += 1
            if self._dirty_requests >= 10 or time.monotonic() - self._last_flush >= 30:
                self._flush_locked()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            self._roll_month_locked()
            return dict(self._state)

    def _flush_locked(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)
        self._dirty_requests = 0
        self._last_flush = time.monotonic()


def _current_month_key() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def load_site_config(path: Path) -> SiteConfig:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        payload = DEFAULT_SITE_CONFIG
    return SiteConfig.model_validate(payload)


def save_site_config(path: Path, configuration: SiteConfig) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            configuration.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, target)


def operations_snapshot(project_root: Path) -> dict[str, object]:
    root = Path(project_root)
    disk = shutil.disk_usage(root)
    states = {}
    state_directory = root / "data" / "state"
    for name in (
        "forecast_collector",
        "global_sounding_collector",
        "wis2_sounding_collector",
        "weather_map_collector",
    ):
        path = state_directory / f"{name}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            modified_at = datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            )
            age_seconds = max(
                0,
                round(
                    (
                        datetime.now(timezone.utc) - modified_at
                    ).total_seconds()
                ),
            )
            states[name] = {
                "available": True,
                "healthy": _collector_healthy(name, payload, age_seconds),
                "modified_at": modified_at.isoformat(),
                "age_seconds": age_seconds,
                "summary": _state_summary(name, payload),
            }
        except (OSError, ValueError, TypeError):
            states[name] = {"available": False, "healthy": False}
    data_usage = {}
    for name in (
        "ecmwf_forecast",
        "wyoming",
        "wis2_soundings",
        "ecmwf",
    ):
        data_usage[name] = _directory_size(root / "data" / "raw" / name)
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "version": VERSION,
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "used_percent": round(disk.used / disk.total * 100, 1),
        },
        "memory": _memory_snapshot(),
        "system": _system_snapshot(),
        "congestion": server_congestion_snapshot(root),
        "collectors": states,
        "data_usage_bytes": data_usage,
    }


def server_congestion_snapshot(project_root: Path) -> dict[str, object]:
    """Return a lightweight three-level server-capacity indicator."""

    root = Path(project_root)
    disk = shutil.disk_usage(root)
    memory = _memory_snapshot()
    system = _system_snapshot()
    load_ratio = system["load_ratio"]
    memory_percent = memory["used_percent"]
    disk_percent = round(disk.used / disk.total * 100, 1)
    level = _congestion_level(load_ratio, memory_percent, disk_percent)
    labels = {1: "拥挤", 2: "较忙", 3: "通畅"}
    return {
        "level": level,
        "label": labels[level],
        "load_ratio": load_ratio,
        "memory_used_percent": memory_percent,
        "disk_used_percent": disk_percent,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _congestion_level(
    load_ratio: float | None,
    memory_percent: float | None,
    disk_percent: float,
) -> int:
    load = load_ratio or 0.0
    memory = memory_percent or 0.0
    if load >= 1.2 or memory >= 90 or disk_percent >= 95:
        return 1
    if load >= 0.7 or memory >= 75 or disk_percent >= 85:
        return 2
    return 3


AdminAction = Literal[
    "forecast",
    "soundings",
    "wis2",
    "weather-map",
]


def request_admin_action(action: AdminAction) -> dict[str, object]:
    helper = Path(
        os.environ.get(
            "METEOSTATION_ADMIN_HELPER",
            "/usr/local/sbin/meteostation-admin-action",
        )
    )
    if not helper.is_file():
        return {
            "accepted": False,
            "action": action,
            "detail": "运维动作助手尚未安装",
        }
    completed = subprocess.run(
        ["sudo", "-n", str(helper), action],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    detail = (completed.stdout or completed.stderr).strip()
    return {
        "accepted": completed.returncode == 0,
        "action": action,
        "detail": detail or f"exit {completed.returncode}",
    }


def _state_summary(name: str, payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {}
    if name == "wis2_sounding_collector":
        return {
            key: payload.get(key)
            for key in (
                "connected",
                "download_count",
                "downloaded_bytes",
                "last_download_at",
            )
        }
    last_run = payload.get("last_run")
    return {
        "updated_at": payload.get("updated_at") or payload.get("checked_at"),
        "last_run": last_run if isinstance(last_run, dict) else None,
        "item_count": (
            len(payload.get("items", {}))
            if isinstance(payload.get("items"), dict)
            else None
        ),
    }


def _collector_healthy(
    name: str,
    payload: object,
    age_seconds: int,
) -> bool:
    maximum_age = {
        "forecast_collector": 600,
        "global_sounding_collector": 600,
        "wis2_sounding_collector": 300,
        "weather_map_collector": 5400,
    }.get(name, 600)
    if age_seconds > maximum_age or not isinstance(payload, dict):
        return False
    if name == "wis2_sounding_collector":
        return payload.get("connected") is True
    return True


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _memory_snapshot() -> dict[str, int | float | None]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            label, raw = line.split(":", 1)
            values[label] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError):
        return {
            "total_bytes": None,
            "available_bytes": None,
            "used_percent": None,
        }
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_percent": (
            round((total - available) / total * 100, 1)
            if total
            else None
        ),
    }


def _system_snapshot() -> dict[str, int | float | None]:
    cpu_count = max(1, os.cpu_count() or 1)
    try:
        load_1m, load_5m, load_15m = os.getloadavg()
    except (AttributeError, OSError):
        load_1m = load_5m = load_15m = 0.0
    try:
        uptime_seconds = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        uptime_seconds = None
    return {
        "cpu_count": cpu_count,
        "load_1m": round(load_1m, 2),
        "load_5m": round(load_5m, 2),
        "load_15m": round(load_15m, 2),
        "load_ratio": round(load_1m / cpu_count, 2),
        "uptime_seconds": (
            round(uptime_seconds) if uptime_seconds is not None else None
        ),
    }
