"""Small, honest ensemble-product core.

The web application may only publish a model when a validated local snapshot
exists.  This module deliberately does not synthesize ensemble members from a
deterministic forecast.  It provides the schema, statistics and clustering
primitives used by a future AIFS ENS or WeatherNext 2 adapter.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


MODEL_CATALOG: dict[str, dict[str, Any]] = {
    "aifs-ens": {
        "label": "AIFS ENS",
        "provider": "ECMWF",
        "source_url": "https://www.ecmwf.int/en/forecasts/datasets/set-x",
        "members": 51,
        "cycle_hours": [0, 6, 12, 18],
        "native_steps": list(range(0, 361, 6)),
        "license": "CC-BY-4.0 + ECMWF Terms of Use",
        "access": "ECMWF Open Data / dissemination",
    },
    "wn2": {
        "label": "WeatherNext 2",
        "provider": "Google DeepMind / Google Research",
        "source_url": "https://deepmind.google/science/weathernext/",
        "members": None,
        "cycle_hours": [0, 6, 12, 18],
        "native_steps": list(range(0, 361, 6)),
        "license": "Provider terms vary by BigQuery, Earth Engine or model release",
        "access": "Official Google distribution or a licensed local adapter",
    },
}


@dataclass(frozen=True)
class EnsembleSnapshot:
    model: str
    initialized_at: datetime
    steps: tuple[int, ...]
    members: int
    variables: tuple[str, ...]
    payload: dict[str, Any]


def _utc(value: str | datetime) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def load_snapshot(path: Path) -> EnsembleSnapshot:
    """Load and validate a compact derived snapshot, never a raw global field."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    model = str(payload["model"]).casefold()
    if model not in MODEL_CATALOG:
        raise ValueError(f"unsupported ensemble model: {model}")
    steps = tuple(int(step) for step in payload["steps"])
    if not steps or list(steps) != sorted(set(steps)):
        raise ValueError("steps must be sorted and unique")
    allowed = set(MODEL_CATALOG[model]["native_steps"])
    if not set(steps).issubset(allowed):
        raise ValueError("snapshot contains non-native forecast steps")
    members = int(payload["members"])
    if members < 2:
        raise ValueError("an ensemble snapshot needs at least two members")
    variables = tuple(str(item) for item in payload.get("variables", []))
    if not variables:
        raise ValueError("snapshot has no variables")
    return EnsembleSnapshot(
        model=model,
        initialized_at=_utc(str(payload["initialized_at"])),
        steps=steps,
        members=members,
        variables=variables,
        payload=payload,
    )


def ensemble_capability_report(project_root: Path) -> dict[str, Any]:
    """Describe what can actually be served from local derived products."""
    report: dict[str, Any] = {}
    root = project_root / "data" / "products" / "ensembles"
    for model, catalog in MODEL_CATALOG.items():
        snapshot_path = root / model / "latest.json"
        item: dict[str, Any] = {**catalog, "model": model}
        if snapshot_path.exists():
            try:
                snapshot = load_snapshot(snapshot_path)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                item.update({"status": "invalid", "detail": str(exc)})
            else:
                item.update(
                    {
                        "status": "available",
                        "initialized_at": snapshot.initialized_at.isoformat(),
                        "steps": list(snapshot.steps),
                        "members": snapshot.members,
                        "variables": list(snapshot.variables),
                        "snapshot": snapshot_path.relative_to(project_root).as_posix(),
                    }
                )
        else:
            item.update(
                {
                    "status": "not_configured",
                    "detail": "No validated local derived snapshot; the UI will not show invented member data.",
                }
            )
        report[model] = item
    return report


def summarize_members(values: Any) -> dict[str, Any]:
    """Return NaN-aware ensemble statistics for shape (member, step)."""
    array = np.asarray(values, dtype=float)
    if array.ndim != 2:
        raise ValueError("member values must have shape (member, step)")
    finite = np.isfinite(array)
    count = finite.sum(axis=0)

    def percentile(q: float) -> list[float | None]:
        result: list[float | None] = []
        for column in array.T:
            valid = column[np.isfinite(column)]
            result.append(float(np.percentile(valid, q)) if valid.size else None)
        return result

    mean = np.nanmean(array, axis=0)
    median = np.nanmedian(array, axis=0)
    std = np.nanstd(array, axis=0)
    return {
        "valid_members": count.astype(int).tolist(),
        "mean": [float(value) if np.isfinite(value) else None for value in mean],
        "median": [float(value) if np.isfinite(value) else None for value in median],
        "std": [float(value) if np.isfinite(value) else None for value in std],
        "p10": percentile(10),
        "p25": percentile(25),
        "p75": percentile(75),
        "p90": percentile(90),
    }


def threshold_support(values: Any, threshold: float, *, operator: str = ">=") -> list[float | None]:
    array = np.asarray(values, dtype=float)
    if array.ndim != 2:
        raise ValueError("member values must have shape (member, step)")
    output: list[float | None] = []
    for column in array.T:
        column = column[np.isfinite(column)]
        if not column.size:
            output.append(None)
            continue
        if operator == ">=":
            output.append(float(np.mean(column >= threshold)))
        elif operator == "<=":
            output.append(float(np.mean(column <= threshold)))
        else:
            raise ValueError("operator must be >= or <=")
    return output


def cluster_scenarios(features: Any, *, k: int = 3, iterations: int = 40) -> list[dict[str, Any]]:
    """Deterministic compact k-means with medoid representatives.

    Features are member rows.  Callers should standardize physically distinct
    variables before passing them.  The result stores distances and member
    indexes so the UI can explain the clustering instead of exposing a score.
    """
    array = np.asarray(features, dtype=float)
    if array.ndim != 2 or array.shape[0] < 2:
        return []
    valid_rows = np.all(np.isfinite(array), axis=1)
    rows = array[valid_rows]
    original_indexes = np.flatnonzero(valid_rows)
    if rows.shape[0] < 2:
        return []
    k = max(1, min(int(k), rows.shape[0]))
    centers = rows[np.linspace(0, rows.shape[0] - 1, k, dtype=int)].copy()
    labels = np.zeros(rows.shape[0], dtype=int)
    for _ in range(max(1, iterations)):
        distances = np.linalg.norm(rows[:, None, :] - centers[None, :, :], axis=2)
        next_labels = np.argmin(distances, axis=1)
        next_centers = centers.copy()
        for cluster in range(k):
            members = rows[next_labels == cluster]
            if members.size:
                next_centers[cluster] = members.mean(axis=0)
        if np.array_equal(labels, next_labels):
            labels = next_labels
            centers = next_centers
            break
        labels = next_labels
        centers = next_centers
    result: list[dict[str, Any]] = []
    for cluster in range(k):
        indexes = np.flatnonzero(labels == cluster)
        if not indexes.size:
            continue
        distances = np.linalg.norm(rows[indexes] - centers[cluster], axis=1)
        medoid_local = indexes[int(np.argmin(distances))]
        result.append(
            {
                "cluster": cluster + 1,
                "member_indexes": original_indexes[indexes].astype(int).tolist(),
                "member_count": int(indexes.size),
                "member_fraction": float(indexes.size / rows.shape[0]),
                "medoid_member_index": int(original_indexes[medoid_local]),
                "within_cluster_distance": float(np.mean(distances)),
                "center": centers[cluster].astype(float).tolist(),
            }
        )
    return result


def stable_snapshot_id(model: str, initialized_at: datetime) -> str:
    value = f"{model.casefold()}|{_utc(initialized_at).isoformat()}".encode()
    return hashlib.sha256(value).hexdigest()[:16]
