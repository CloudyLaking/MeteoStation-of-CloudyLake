"""Storage-light access to real AIFS ENS and WeatherNext 2 point forecasts."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .ensemble import summarize_members


OPEN_METEO_ENDPOINT = "https://ensemble-api.open-meteo.com/v1/ensemble"
MODEL_IDS = {
    "aifs-ens": "ecmwf_aifs025",
    "wn2": "google_weathernext2_ensemble",
}
VARIABLES = {
    "temperature_2m": "2米气温",
    "precipitation": "时段降水",
    "wind_speed_10m": "10米风速",
    "pressure_msl": "海平面气压",
}
_cache: dict[tuple[str, float, float], tuple[float, dict[str, Any]]] = {}
_cache_lock = asyncio.Lock()
_CACHE_SECONDS = 30 * 60


def _member_keys(hourly: dict[str, Any], variable: str) -> list[str]:
    keys = [variable] if isinstance(hourly.get(variable), list) else []
    keys.extend(
        sorted(
            key
            for key, value in hourly.items()
            if key.startswith(f"{variable}_member") and isinstance(value, list)
        )
    )
    return keys


def normalize_point_payload(model: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and compact an Open-Meteo native ensemble response."""
    hourly = payload.get("hourly")
    units = payload.get("hourly_units", {})
    if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
        raise ValueError("集合资料缺少有效时间轴")
    times = [str(value) for value in hourly["time"]]
    products: dict[str, Any] = {}
    member_count = 0
    for variable, label in VARIABLES.items():
        keys = _member_keys(hourly, variable)
        rows = [hourly[key] for key in keys]
        if not rows or any(len(row) != len(times) for row in rows):
            continue
        member_count = max(member_count, len(rows))
        products[variable] = {
            "label": label,
            "unit": units.get(variable, ""),
            "members": rows,
            "statistics": summarize_members(rows),
        }
    if not products or member_count < 2:
        raise ValueError("上游响应中没有可用的集合成员")
    return {
        "model": model,
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "elevation_m": payload.get("elevation"),
        "timezone": payload.get("timezone", "GMT"),
        "times": times,
        "members": member_count,
        "native_step_hours": 6,
        "forecast_hours": min(360, max(0, (len(times) - 1) * 6)),
        "variables": products,
        "source": {
            "provider": "Open-Meteo Ensemble API",
            "upstream_model": MODEL_IDS[model],
            "url": "https://open-meteo.com/en/docs/ensemble-api",
            "note": "按需获取逐点原生成员；本站仅作短时内存缓存，不保存全球原始场。",
        },
    }


async def fetch_point_ensemble(model: str, latitude: float, longitude: float) -> dict[str, Any]:
    model = model.casefold()
    if model not in MODEL_IDS:
        raise ValueError("不支持的集合模型")
    # A quarter-degree key prevents a public endpoint from becoming an
    # unbounded coordinate cache. The upstream also snaps to its model grid.
    key = (model, round(latitude * 4) / 4, round(longitude * 4) / 4)
    now = time.monotonic()
    async with _cache_lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < _CACHE_SECONDS:
            return {**cached[1], "cache": "hit"}

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(VARIABLES),
        "models": MODEL_IDS[model],
        "temporal_resolution": "native",
        "forecast_days": 16,
        "timezone": "GMT",
    }
    timeout = httpx.Timeout(25.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(OPEN_METEO_ENDPOINT, params=params)
        response.raise_for_status()
        result = normalize_point_payload(model, response.json())
    async with _cache_lock:
        if len(_cache) >= 96:
            oldest = min(_cache, key=lambda item: _cache[item][0])
            _cache.pop(oldest, None)
        _cache[key] = (time.monotonic(), result)
    return {**result, "cache": "miss"}
