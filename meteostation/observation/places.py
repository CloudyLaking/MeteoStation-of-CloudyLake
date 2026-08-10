"""Chinese administrative place index used for location search.

Names and centre coordinates come from the DataV GeoAtlas public dataset:
provinces are cached under ``data/geo/provinces.json`` (downloaded on first
use, same file the station map relies on) and cities come from the bundled
``中国_市.geojson``. Cached district layers (``data/geo/district_*.json``)
are merged in as they become available, so the index grows to cover
counties/districts without extra downloads beyond what the map already does.
"""

import json
import urllib.request
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CITY_GEOJSON = PROJECT_ROOT / "中国_市.geojson"
GEO_CACHE = PROJECT_ROOT / "data" / "geo"
PROVINCES_CACHE = GEO_CACHE / "provinces.json"
PROVINCES_URL = "https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json"


def _province_features() -> list[dict[str, object]]:
    if PROVINCES_CACHE.exists():
        try:
            payload = json.loads(PROVINCES_CACHE.read_text(encoding="utf-8"))
            features = list(payload.get("features", []))
            if features:
                return features
        except (OSError, ValueError):
            pass
    try:
        request = urllib.request.Request(
            PROVINCES_URL,
            headers={"User-Agent": "MeteoStation/2.2.1"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        features = list(payload.get("features", []))
        GEO_CACHE.mkdir(parents=True, exist_ok=True)
        PROVINCES_CACHE.write_text(
            json.dumps(
                {"type": "FeatureCollection", "features": features},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return features
    except Exception:
        return []


def _record_from_feature(
    feature: object,
    *,
    fallback_level: str,
) -> dict[str, object] | None:
    if not isinstance(feature, dict):
        return None
    props = feature.get("properties") or {}
    name = props.get("name")
    center = props.get("center")
    if not name or not isinstance(center, list) or len(center) != 2:
        return None
    return {
        "name": str(name),
        "adcode": str(props.get("adcode", "")),
        "level": str(props.get("level", fallback_level)),
        "longitude": float(center[0]),
        "latitude": float(center[1]),
    }


@lru_cache(maxsize=1)
def place_records() -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for feature in _province_features():
        record = _record_from_feature(feature, fallback_level="province")
        if record:
            records.append(record)
    if CITY_GEOJSON.exists():
        try:
            cities = json.loads(CITY_GEOJSON.read_text(encoding="utf-8"))
            for feature in cities.get("features", []):
                record = _record_from_feature(feature, fallback_level="city")
                if record and record["level"] != "province":
                    records.append(record)
        except (OSError, ValueError):
            pass
    if GEO_CACHE.is_dir():
        for path in sorted(GEO_CACHE.glob("district_*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for feature in payload.get("features", []):
                record = _record_from_feature(feature, fallback_level="district")
                if record:
                    records.append(record)
    # Keep the most specific record for a duplicated name (province vs city).
    seen: dict[str, dict[str, object]] = {}
    for record in records:
        name = str(record["name"])
        rank = {"province": 0, "city": 1, "district": 2}.get(record["level"], 1)
        if name not in seen or rank > seen[name]["_rank"]:
            seen[name] = {**record, "_rank": rank}
    return tuple(
        {key: value for key, value in record.items() if key != "_rank"}
        for record in seen.values()
    )


def search_places(query: str, *, limit: int = 8) -> list[dict[str, object]]:
    normalized = query.strip().casefold()
    if not normalized:
        return []
    exact: list[dict[str, object]] = []
    partial: list[dict[str, object]] = []
    for record in place_records():
        name = str(record["name"]).casefold()
        if normalized == name:
            exact.append(record)
        elif normalized in name:
            partial.append(record)
    return (exact + partial)[:limit]


def resolve_place(query: str) -> dict[str, object] | None:
    normalized = query.strip().casefold()
    if not normalized:
        return None
    for record in place_records():
        if str(record["name"]).casefold() == normalized:
            return record
    return None
