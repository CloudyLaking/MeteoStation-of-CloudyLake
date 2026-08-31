from __future__ import annotations

import hashlib
import json
import queue
import re
import ssl
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock
from urllib.parse import urlparse

import httpx
import paho.mqtt.client as mqtt
from pydantic import BaseModel, Field

from .collector import load_json, write_json_atomic


class Wis2CollectorConfig(BaseModel):
    broker_host: str
    broker_port: int = Field(default=8883, ge=1, le=65535)
    username: str = "everyone"
    password: str = "everyone"
    keepalive_seconds: int = Field(default=60, ge=30, le=300)
    retention_days: int = Field(default=3, ge=1, le=30)
    topics: list[str]
    allowed_station_ids: set[str] = Field(default_factory=set)


def load_wis2_config(path: Path) -> Wis2CollectorConfig:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    allowlist_file = raw.pop("allowed_station_ids_file", None)
    if allowlist_file:
        inventory = json.loads((path.parent / str(allowlist_file)).read_text(encoding="utf-8"))
        raw["allowed_station_ids"] = [
            str(item["wmo_id"])
            for item in inventory.get("stations", [])
            if isinstance(item, dict) and str(item.get("wmo_id", "")).isdigit()
        ]
    return Wis2CollectorConfig.model_validate(raw)


class Wis2SoundingCollector:
    """Archive real-time WIS2 TEMP notifications and their canonical BUFR."""

    def __init__(
        self,
        *,
        config: Wis2CollectorConfig,
        archive_root: Path,
        state_path: Path,
    ) -> None:
        self.config = config
        self.archive_root = Path(archive_root)
        self.state_path = Path(state_path)
        self.messages: queue.Queue[tuple[str, bytes]] = queue.Queue(maxsize=5000)
        self.stop_event = Event()
        self.skipped_notifications = 0
        self.state_lock = Lock()
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="cloudylake-wis2-temp",
            protocol=mqtt.MQTTv5,
        )
        self.client.username_pw_set(config.username, config.password)
        self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def run_forever(self) -> None:
        self.archive_root.mkdir(parents=True, exist_ok=True)
        last_prune_at = 0.0
        self.client.connect(
            self.config.broker_host,
            self.config.broker_port,
            self.config.keepalive_seconds,
        )
        self.client.loop_start()
        try:
            with httpx.Client(
                timeout=60,
                follow_redirects=True,
                headers={"User-Agent": "CloudyLake-Observatory/2.1.1"},
            ) as http:
                while not self.stop_event.is_set():
                    if time.monotonic() - last_prune_at >= 15 * 60:
                        self.prune()
                        last_prune_at = time.monotonic()
                    try:
                        topic, payload = self.messages.get(timeout=30)
                    except queue.Empty:
                        self._write_health()
                        self.prune()
                        continue
                    try:
                        self.archive_notification(http, topic, payload)
                    except (ValueError, httpx.HTTPError, OSError) as exc:
                        self._record_error(str(exc))
                    finally:
                        self.messages.task_done()
        finally:
            self.client.loop_stop()
            self.client.disconnect()

    def archive_notification(
        self,
        http: httpx.Client,
        topic: str,
        payload: bytes,
    ) -> Path:
        notification = json.loads(payload.decode("utf-8"))
        href = find_bufr_href(notification)
        if href is None:
            raise ValueError("WIS2 TEMP notification has no downloadable link")
        observed_at = notification_datetime(notification)
        notification_id = str(
            notification.get("id")
            or hashlib.sha256(payload).hexdigest()
        )
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", notification_id)[:120]
        directory = (
            self.archive_root
            / f"{observed_at:%Y}"
            / f"{observed_at:%m}"
            / f"{observed_at:%d}"
        )
        suffix = Path(urlparse(href).path).suffix or ".bufr"
        data_path = directory / f"{safe_id}{suffix}"
        metadata_path = directory / f"{safe_id}.json"
        if data_path.exists() and metadata_path.exists():
            return data_path

        response = http.get(href)
        response.raise_for_status()
        content = response.content
        directory.mkdir(parents=True, exist_ok=True)
        temporary = data_path.with_suffix(data_path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(data_path)
        write_json_atomic(
            metadata_path,
            {
                "notification_id": notification_id,
                "topic": topic,
                "observed_at": observed_at.isoformat(),
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "source_url": href,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "notification": notification,
            },
        )
        properties = notification.get("properties", {})
        station_id = str(properties.get("station_identifier", "")) if isinstance(properties, dict) else ""
        if station_id.isdigit() and len(station_id) == 5:
            index_path = directory / "index.json"
            index = load_json(index_path, default={"items": {}})
            items = index.setdefault("items", {})
            cycle_at = observed_at.replace(minute=0, second=0, microsecond=0)
            key = f"{station_id}|{cycle_at.isoformat()}"
            entries = items.setdefault(key, [])
            record = {
                "data_file": data_path.name,
                "metadata_file": metadata_path.name,
                "source_url": href,
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
            }
            if not any(item.get("data_file") == data_path.name for item in entries):
                entries.append(record)
            index["updated_at"] = datetime.now(timezone.utc).isoformat()
            write_json_atomic(index_path, index)
        self._record_download(len(content))
        return data_path

    def prune(self, reference_time: datetime | None = None) -> dict[str, int]:
        now = reference_time or datetime.now(timezone.utc)
        cutoff = now.date() - timedelta(days=self.config.retention_days)
        root = self.archive_root.resolve()
        removed_files = 0
        removed_directories = 0
        if not root.exists():
            return {"files": 0, "directories": 0}
        for year_dir in root.iterdir():
            for month_dir in year_dir.iterdir() if year_dir.is_dir() else []:
                for day_dir in month_dir.iterdir() if month_dir.is_dir() else []:
                    try:
                        archive_date = datetime.strptime(
                            f"{year_dir.name}-{month_dir.name}-{day_dir.name}",
                            "%Y-%m-%d",
                        ).date()
                    except ValueError:
                        continue
                    resolved = day_dir.resolve()
                    if archive_date >= cutoff or root not in resolved.parents:
                        continue
                    files = [item for item in resolved.rglob("*") if item.is_file()]
                    removed_files += len(files)
                    for item in files:
                        item.unlink()
                    for child in sorted(
                        (item for item in resolved.rglob("*") if item.is_dir()),
                        reverse=True,
                    ):
                        child.rmdir()
                    resolved.rmdir()
                    removed_directories += 1
        return {"files": removed_files, "directories": removed_directories}

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code != 0:
            self._record_error(f"MQTT connection rejected: {reason_code}")
            return
        for topic in self.config.topics:
            client.subscribe(topic, qos=1)
        self._write_health(connected=True)

    def _on_message(self, client, userdata, message) -> None:
        try:
            payload = bytes(message.payload)
            if self.config.allowed_station_ids:
                notification = json.loads(payload.decode("utf-8"))
                properties = notification.get("properties", {})
                station_id = str(properties.get("station_identifier", "")) if isinstance(properties, dict) else ""
                if station_id not in self.config.allowed_station_ids:
                    self.skipped_notifications += 1
                    return
            self.messages.put_nowait((message.topic, payload))
        except queue.Full:
            self._record_error("WIS2 notification queue is full")
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self._record_error("WIS2 notification is not valid JSON")

    def _on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties,
    ) -> None:
        self._write_health(connected=False, message=str(reason_code))

    def _write_health(
        self,
        *,
        connected: bool | None = None,
        message: str | None = None,
    ) -> None:
        with self.state_lock:
            state = load_json(self.state_path, default={})
            state["checked_at"] = datetime.now(timezone.utc).isoformat()
            if connected is not None:
                state["connected"] = connected
                if connected:
                    state.pop("message", None)
            if message is not None:
                state["message"] = message
            state["queued_notifications"] = self.messages.qsize()
            state["skipped_notifications"] = self.skipped_notifications
            state["station_filter_count"] = len(self.config.allowed_station_ids)
            write_json_atomic(self.state_path, state)

    def _record_download(self, byte_count: int) -> None:
        with self.state_lock:
            state = load_json(self.state_path, default={})
            state["download_count"] = int(state.get("download_count", 0)) + 1
            state["downloaded_bytes"] = (
                int(state.get("downloaded_bytes", 0)) + byte_count
            )
            state["last_download_at"] = datetime.now(timezone.utc).isoformat()
            state["connected"] = True
            state.pop("message", None)
            write_json_atomic(self.state_path, state)

    def _record_error(self, message: str) -> None:
        with self.state_lock:
            state = load_json(self.state_path, default={})
            state["error_count"] = int(state.get("error_count", 0)) + 1
            state["last_error_at"] = datetime.now(timezone.utc).isoformat()
            state["last_error"] = message
            write_json_atomic(self.state_path, state)


def find_bufr_href(notification: object) -> str | None:
    candidates: list[tuple[int, str]] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            href = value.get("href")
            if isinstance(href, str) and href.startswith(("https://", "http://")):
                rel = str(value.get("rel", "")).lower()
                media_type = str(value.get("type", "")).lower()
                path = urlparse(href).path.lower()
                score = 0
                if rel in {"canonical", "data"}:
                    score += 4
                if "bufr" in media_type:
                    score += 4
                if path.endswith((".bufr", ".bufr4", ".bin")):
                    score += 2
                candidates.append((score, href))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(notification)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def notification_datetime(notification: dict[str, object]) -> datetime:
    values = [
        notification.get("properties", {}).get("datetime")
        if isinstance(notification.get("properties"), dict)
        else None,
        notification.get("time"),
    ]
    for value in values:
        if not isinstance(value, str):
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)
