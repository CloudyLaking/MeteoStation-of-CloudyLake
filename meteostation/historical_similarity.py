"""Explainable, lightweight historical-cyclone similarity scoring."""

from __future__ import annotations

from typing import Any


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def similarity_score(current: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Return components, not an opaque single percentage."""
    path = _bounded(1.0 - float(current.get("path_distance_km", 9999.0)) / 2500.0)
    intensity = _bounded(1.0 - abs(float(current.get("max_wind_kt", 0.0)) - float(candidate.get("max_wind_kt", 0.0))) / 80.0)
    season = 1.0 if int(current.get("month", 0)) == int(candidate.get("month", -1)) else 0.5
    steering = _bounded(1.0 - float(current.get("environment_distance", 9999.0)) / 6.0)
    components = {"path": path, "intensity": intensity, "season": season, "environment": steering}
    weights = {"path": 0.35, "intensity": 0.2, "season": 0.15, "environment": 0.3}
    total = sum(components[key] * weights[key] for key in components)
    return {
        "score": round(total, 4),
        "components": {key: round(value, 4) for key, value in components.items()},
        "weights": weights,
        "disclaimer": "相似不代表结果相同 / Similarity does not imply the same outcome.",
    }
