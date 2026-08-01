"""Small, secret-free wrapper around the authenticated ECMWF MARS Web API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class MarsClientUnavailable(RuntimeError):
    pass


class MarsAccessUnavailable(RuntimeError):
    pass


def retrieve_mars(
    request: dict[str, object],
    target: Path,
) -> Path:
    """Execute one MARS request and atomically publish its output."""
    try:
        from ecmwfapi import ECMWFService
    except ImportError as exc:
        raise MarsClientUnavailable(
            "缺少 ecmwf-api-client；请安装 requirements-weather-map.txt。"
        ) from exc

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.part")
    temporary.unlink(missing_ok=True)
    try:
        ECMWFService("mars").execute(request, str(temporary))
        if not temporary.exists() or temporary.stat().st_size == 0:
            raise RuntimeError("ECMWF MARS returned an empty file")
        os.replace(temporary, target)
    except Exception as exc:
        message = str(exc)
        if "no access to services/mars" in message.casefold():
            raise MarsAccessUnavailable(
                "当前 ECMWF 账户尚未开通 services/mars"
            ) from exc
        raise
    finally:
        temporary.unlink(missing_ok=True)
    return target


def mars_point_area(
    latitude: float,
    longitude: float,
    *,
    radius_degrees: float = 0.25,
) -> str:
    """Return a small N/W/S/E box suitable for station interpolation."""
    north = min(90.0, latitude + radius_degrees)
    south = max(-90.0, latitude - radius_degrees)
    west = longitude - radius_degrees
    east = longitude + radius_degrees
    return f"{north:.4f}/{west:.4f}/{south:.4f}/{east:.4f}"


def mars_model_keywords(model: str) -> dict[str, Any]:
    if model == "aifs":
        return {
            "class": "ai",
            "model": "aifs-single",
            "expver": "1",
        }
    return {
        "class": "od",
        "expver": "1",
    }
