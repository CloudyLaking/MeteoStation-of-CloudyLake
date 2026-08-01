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

from pydantic import BaseModel, Field, field_validator


VERSION = "V2.1.1"
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
        "notice": "资料持续自动更新；分析结论仅供学习与研究参考。",
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
    notice: str = Field(min_length=2, max_length=160)


class SiteConfig(BaseModel):
    version: str = VERSION
    theme: ThemeConfig = Field(default_factory=ThemeConfig)
    homepage: HomepageConfig = Field(
        default_factory=lambda: HomepageConfig(
            **DEFAULT_SITE_CONFIG["homepage"],
        )
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
        default = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "requests": 0,
            "response_bytes": 0,
            "status_counts": {},
            "path_counts": {},
            "last_request_at": None,
        }
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return default
        return {**default, **loaded}

    def record(self, path: str, status_code: int, response_bytes: int) -> None:
        if path.startswith("/static/") or path.startswith("/brand/"):
            category = "static"
        elif path.startswith("/api/"):
            category = "api"
        else:
            category = "page"
        with self._lock:
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
            self._state["last_request_at"] = datetime.now(timezone.utc).isoformat()
            self._dirty_requests += 1
            if self._dirty_requests >= 10 or time.monotonic() - self._last_flush >= 30:
                self._flush_locked()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
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
            states[name] = {
                "available": True,
                "modified_at": modified_at.isoformat(),
                "age_seconds": max(
                    0,
                    round(
                        (
                            datetime.now(timezone.utc) - modified_at
                        ).total_seconds()
                    ),
                ),
                "summary": _state_summary(name, payload),
            }
        except (OSError, ValueError, TypeError):
            states[name] = {"available": False}
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
        "collectors": states,
        "data_usage_bytes": data_usage,
    }


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
