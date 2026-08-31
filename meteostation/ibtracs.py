"""Compact IBTrACS index access and explainable historical analog ranking."""

from __future__ import annotations

import gzip
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from .cyclone_products import haversine_km


@lru_cache(maxsize=2)
def load_index(path_string: str) -> list[dict[str, Any]]:
    path = Path(path_string)
    if not path.exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("storms", [])


def search_storms(path: Path, query: str = "", limit: int = 30) -> list[dict[str, Any]]:
    query = query.strip().casefold()
    storms = load_index(str(path.resolve()))
    matches = [storm for storm in storms if not query or query in str(storm.get("sid", "")).casefold() or query in str(storm.get("name", "")).casefold()]
    matches.sort(key=lambda storm: (int(storm.get("season", 0)), str(storm.get("sid", ""))), reverse=True)
    return [{key: storm.get(key) for key in ("sid", "name", "season", "basin", "max_wind_kt", "start_time", "end_time")} for storm in matches[:limit]]


def _sample(points: list[dict[str, Any]], count: int = 18) -> list[dict[str, Any]]:
    if len(points) <= count:
        return points
    return [points[round(index * (len(points) - 1) / (count - 1))] for index in range(count)]


def _track_distance(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> float:
    left, right = _sample(left), _sample(right)
    count = min(len(left), len(right))
    if count < 2:
        return float("inf")
    return sum(haversine_km(float(left[round(i*(len(left)-1)/(count-1))]["lat"]), float(left[round(i*(len(left)-1)/(count-1))]["lon"]), float(right[round(i*(len(right)-1)/(count-1))]["lat"]), float(right[round(i*(len(right)-1)/(count-1))]["lon"])) for i in range(count)) / count


def analogs(path: Path, sid: str, limit: int = 10) -> dict[str, Any] | None:
    storms = load_index(str(path.resolve()))
    target = next((storm for storm in storms if storm.get("sid") == sid), None)
    if target is None:
        return None
    ranked = []
    target_month = int(str(target.get("start_time", "0000-01"))[5:7] or 1)
    for storm in storms:
        if storm.get("sid") == sid or storm.get("basin") != target.get("basin") or len(storm.get("points", [])) < 3:
            continue
        distance = _track_distance(target["points"], storm["points"])
        path_score = max(0.0, 1 - distance / 3000)
        wind_delta = abs(float(target.get("max_wind_kt") or 0) - float(storm.get("max_wind_kt") or 0))
        intensity_score = max(0.0, 1 - wind_delta / 90)
        month = int(str(storm.get("start_time", "0000-01"))[5:7] or 1)
        month_delta = min(abs(month-target_month), 12-abs(month-target_month))
        season_score = max(0.0, 1 - month_delta / 4)
        total = .55 * path_score + .30 * intensity_score + .15 * season_score
        ranked.append({
            "sid": storm.get("sid"), "name": storm.get("name"), "season": storm.get("season"), "score": round(total, 4),
            "components": {"path": round(path_score, 4), "intensity": round(intensity_score, 4), "season": round(season_score, 4), "era5_environment": None},
            "track_distance_km": round(distance, 1), "max_wind_kt": storm.get("max_wind_kt"), "points": storm.get("points", []),
            "era5_link": f"/reanalysis?date={str(storm.get('start_time',''))[:10]}",
        })
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return {"target": target, "analogs": ranked[:limit], "weights": {"path": .55, "intensity": .30, "season": .15}, "era5_environment": "可从案例日期打开 ERA5；环境场加入评分前保持为空。"}
