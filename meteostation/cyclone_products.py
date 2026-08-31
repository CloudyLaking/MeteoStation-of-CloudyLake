"""Transparent WNC product primitives and identity helpers.

No WN2 or deterministic track is promoted to a WNC member.  The functions in
this module operate only on a validated WNC snapshot supplied by an adapter.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


WNC_SOURCE = {
    "label": "WeatherNext Cyclones",
    "source_url": "https://deepmind.google/blog/weathernext-ai-model-achieves-breakthrough-in-forecasting-cyclones/",
    "weather_lab_url": "https://www.weatherlab.ai/",
    "member_target": 1000,
    "lead_time_hours": 360,
    "status": "not_configured",
    "detail": "No compliant local WNC feed or remote inference job is configured.",
}


def load_wnc_snapshot(path: Path) -> dict[str, Any]:
    """Validate a compact WNC-derived product without accepting substitutes."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = str(payload.get("source", "")).casefold()
    if "weathernext cyclones" not in source:
        raise ValueError("snapshot source must explicitly be WeatherNext Cyclones")
    members = int(payload["members"])
    if not 1 <= members <= 1000:
        raise ValueError("members must be between 1 and 1000")
    systems = payload.get("systems")
    if not isinstance(systems, list):
        raise ValueError("systems must be a list")
    normalized = []
    for system in systems:
        if not isinstance(system, dict) or not system.get("system_id"):
            raise ValueError("every system needs a system_id")
        clusters = system.get("clusters", [])
        if not isinstance(clusters, list):
            raise ValueError("clusters must be a list")
        for cluster in clusters:
            points = cluster.get("representative_track", [])
            if not isinstance(points, list) or any("lat" not in point or "lon" not in point for point in points):
                raise ValueError("cluster representative tracks need lat/lon points")
        normalized.append({
            "system_id": str(system["system_id"]),
            "name": system.get("name"),
            "basin": system.get("basin"),
            "identity_confidence": system.get("identity_confidence"),
            "genesis_probability": system.get("genesis_probability"),
            "clusters": clusters,
        })
    return {
        "source": payload["source"],
        "source_url": payload.get("source_url", WNC_SOURCE["source_url"]),
        "initialized_at": payload.get("initialized_at"),
        "members": members,
        "systems": normalized,
        "system_count": len(normalized),
        "storage_class": "derived-track-product",
    }


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def stable_system_id(basin: str, season: int, first_time: str | datetime, first_lat: float, first_lon: float) -> str:
    """Make an internal id stable across source-name changes and re-runs."""
    key = f"{basin.casefold()}|{int(season)}|{_utc(first_time).isoformat()}|{first_lat:.2f}|{first_lon:.2f}"
    return "sys-" + hashlib.sha256(key.encode()).hexdigest()[:18]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def trajectory_distance(track_a: list[dict[str, Any]], track_b: list[dict[str, Any]]) -> float:
    """Mean nearest-time distance in km, tolerant of unequal track lengths."""
    if not track_a or not track_b:
        return float("inf")
    distances: list[float] = []
    for point in track_a:
        nearest = min(
            haversine_km(float(point["lat"]), float(point["lon"]), float(other["lat"]), float(other["lon"]))
            for other in track_b
        )
        distances.append(nearest)
    return float(np.mean(distances))


def cluster_tracks(tracks: list[list[dict[str, Any]]], *, radius_km: float = 350.0) -> list[dict[str, Any]]:
    """Greedy connected clustering for a small derived WNC track set.

    This is intentionally conservative and explainable.  A production adapter
    can replace it with HDBSCAN/DTW while keeping the returned contract.
    """
    clusters: list[list[int]] = []
    for index, track in enumerate(tracks):
        attached = None
        for cluster_index, members in enumerate(clusters):
            if any(trajectory_distance(track, tracks[member]) <= radius_km for member in members):
                attached = cluster_index
                break
        if attached is None:
            clusters.append([index])
        else:
            clusters[attached].append(index)
    result: list[dict[str, Any]] = []
    total = len(tracks)
    for number, members in enumerate(clusters, start=1):
        pair_scores = {
            member: float(np.mean([trajectory_distance(tracks[member], tracks[other]) for other in members]))
            for member in members
        }
        medoid = min(pair_scores, key=pair_scores.get)
        result.append(
            {
                "cluster": number,
                "member_indexes": members,
                "member_count": len(members),
                "member_support_rate": (len(members) / total) if total else None,
                "medoid_member_index": medoid,
                "mean_track_distance_km": pair_scores[medoid],
                "radius_km": radius_km,
            }
        )
    return result


def match_system_identity(track: dict[str, Any], candidates: list[dict[str, Any]], *, max_distance_km: float = 300.0) -> dict[str, Any] | None:
    """Match a member to an existing system only with time/space evidence."""
    best: dict[str, Any] | None = None
    for candidate in candidates:
        distance = trajectory_distance(track.get("points", []), candidate.get("points", []))
        if distance > max_distance_km:
            continue
        score = max(0.0, 1.0 - distance / max_distance_km)
        if best is None or score > float(best["identity_confidence"]):
            best = {
                "system_id": candidate.get("system_id"),
                "identity_confidence": round(score, 4),
                "distance_km": round(distance, 2),
                "match_basis": "trajectory-space-and-time",
            }
    return best


def cyclone_capability_report(project_root: Path) -> dict[str, Any]:
    path = project_root / "data" / "products" / "cyclones" / "wnc-latest.json"
    report = {**WNC_SOURCE}
    if not path.exists():
        return report
    try:
        payload = load_wnc_snapshot(path)
        report.update({"status": "available", "members": payload["members"], "systems": payload["system_count"], "snapshot": path.relative_to(project_root).as_posix(), "initialized_at": payload.get("initialized_at")})
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        report.update({"status": "invalid", "detail": str(exc)})
    return report
