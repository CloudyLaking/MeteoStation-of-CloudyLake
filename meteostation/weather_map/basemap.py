from __future__ import annotations

import io
import json
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import requests
from PIL import Image
from scipy.ndimage import map_coordinates

from .models import WeatherMapDomain


TIANDITU_SUPPORTED_LAYERS = {
    "vec_w": "vec",
    "cva_w": "cva",
    "ibo_w": "ibo",
}


class TiandituBasemapUnavailable(RuntimeError):
    """Raised when the configured official map tiles cannot be assembled."""


@dataclass(frozen=True)
class TiandituBasemap:
    vector: np.ndarray
    labels: np.ndarray
    boundaries: np.ndarray
    extent: tuple[float, float, float, float]
    zoom: int
    source_review_number: str


@dataclass(frozen=True)
class LocalBoundaryLayer:
    province_lines: tuple[np.ndarray, ...]
    boundary_lines: tuple[np.ndarray, ...]
    source: str
    source_path: str
    crs: str
    feature_count: int
    sha256: str


def build_tianditu_wmts_url(
    *,
    layer: str,
    tile_matrix: int,
    tile_row: int,
    tile_column: int,
    token: str,
    server: int = 0,
) -> str:
    """Build one official TianDiTu Web-Mercator WMTS tile request."""
    if layer not in TIANDITU_SUPPORTED_LAYERS:
        raise ValueError(f"Unsupported TianDiTu layer: {layer}")
    if not token.strip():
        raise ValueError("TIANDITU_TOKEN is required")
    if server not in range(8):
        raise ValueError("TianDiTu server must be between 0 and 7")
    layer_name = TIANDITU_SUPPORTED_LAYERS[layer]
    query = urlencode(
        {
            "SERVICE": "WMTS",
            "REQUEST": "GetTile",
            "VERSION": "1.0.0",
            "LAYER": layer_name,
            "STYLE": "default",
            "TILEMATRIXSET": "w",
            "FORMAT": "tiles",
            "TILEMATRIX": tile_matrix,
            "TILEROW": tile_row,
            "TILECOL": tile_column,
            "tk": token,
        }
    )
    return (
        f"https://t{server}.tianditu.gov.cn/{layer}/wmts?"
        f"{query}"
    )


def load_tianditu_basemap(
    *,
    domain: WeatherMapDomain,
    token: str,
    cache_directory: Path,
    zoom: int = 5,
    output_width: int = 1500,
    source_review_number: str = "GS（2024）0568号",
) -> TiandituBasemap:
    """Fetch and warp official TianDiTu tiles to a regular lon/lat image."""
    if not token.strip():
        raise TiandituBasemapUnavailable("TIANDITU_TOKEN is required")
    if zoom < 1 or zoom > 18:
        raise ValueError("zoom must be between 1 and 18")
    output_height = max(
        1,
        round(
            output_width
            * (domain.north - domain.south)
            / (domain.east - domain.west)
        ),
    )
    layers = {
        layer: _load_and_warp_layer(
            layer=layer,
            domain=domain,
            token=token,
            cache_directory=cache_directory,
            zoom=zoom,
            output_width=output_width,
            output_height=output_height,
        )
        for layer in ("vec_w", "cva_w", "ibo_w")
    }
    return TiandituBasemap(
        vector=layers["vec_w"],
        labels=layers["cva_w"],
        boundaries=layers["ibo_w"],
        extent=(domain.west, domain.east, domain.south, domain.north),
        zoom=zoom,
        source_review_number=source_review_number,
    )


def load_geojson_boundary(
    path: Path,
    *,
    source: str,
) -> LocalBoundaryLayer:
    """Load province polygons and explicit boundary lines without mutation."""
    resolved = Path(path)
    raw = resolved.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError("Boundary GeoJSON must be a FeatureCollection")
    crs = str(
        payload.get("crs", {})
        .get("properties", {})
        .get("name", "")
    )
    if not (crs.endswith("4490") or crs.endswith("4326")):
        raise ValueError(
            "Boundary GeoJSON must use EPSG:4490 or EPSG:4326"
        )
    province_lines: list[np.ndarray] = []
    boundary_lines: list[np.ndarray] = []
    features = payload.get("features", [])
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") or {}
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        if geometry_type == "MultiPolygon":
            for polygon in coordinates or []:
                for ring in polygon:
                    _append_boundary_line(province_lines, ring)
        elif geometry_type == "Polygon":
            for ring in coordinates or []:
                _append_boundary_line(province_lines, ring)
        elif geometry_type == "MultiLineString":
            for line in coordinates or []:
                _append_boundary_line(boundary_lines, line)
        elif geometry_type == "LineString":
            _append_boundary_line(boundary_lines, coordinates)
    if not province_lines or not boundary_lines:
        raise ValueError(
            "Boundary GeoJSON must contain province polygons and boundary lines"
        )
    return LocalBoundaryLayer(
        province_lines=tuple(province_lines),
        boundary_lines=tuple(boundary_lines),
        source=source,
        source_path=resolved.name,
        crs=crs,
        feature_count=len(features),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _load_and_warp_layer(
    *,
    layer: str,
    domain: WeatherMapDomain,
    token: str,
    cache_directory: Path,
    zoom: int,
    output_width: int,
    output_height: int,
) -> np.ndarray:
    tile_count = 2**zoom
    x_start = max(0, int(math.floor(_longitude_to_tile_x(domain.west, zoom))))
    x_stop = min(
        tile_count - 1,
        int(math.floor(_longitude_to_tile_x(domain.east, zoom))),
    )
    y_start = max(0, int(math.floor(_latitude_to_tile_y(domain.north, zoom))))
    y_stop = min(
        tile_count - 1,
        int(math.floor(_latitude_to_tile_y(domain.south, zoom))),
    )
    mosaic = Image.new(
        "RGBA",
        (
            (x_stop - x_start + 1) * 256,
            (y_stop - y_start + 1) * 256,
        ),
        (255, 255, 255, 0),
    )
    for tile_y in range(y_start, y_stop + 1):
        for tile_x in range(x_start, x_stop + 1):
            tile = _load_tile(
                layer=layer,
                zoom=zoom,
                tile_x=tile_x,
                tile_y=tile_y,
                token=token,
                cache_directory=cache_directory,
            )
            mosaic.paste(
                tile,
                ((tile_x - x_start) * 256, (tile_y - y_start) * 256),
                tile,
            )

    longitude = np.linspace(domain.west, domain.east, output_width)
    latitude = np.linspace(domain.north, domain.south, output_height)
    global_x = _longitude_to_tile_x(longitude, zoom) * 256
    global_y = _latitude_to_tile_y(latitude, zoom) * 256
    sample_x = global_x - x_start * 256
    sample_y = global_y - y_start * 256
    source = np.asarray(mosaic, dtype=float)
    warped = np.empty((output_height, output_width, 4), dtype=np.uint8)
    coordinates = np.meshgrid(sample_y, sample_x, indexing="ij")
    for channel in range(4):
        values = map_coordinates(
            source[:, :, channel],
            coordinates,
            order=1,
            mode="nearest",
        )
        warped[:, :, channel] = np.clip(values, 0, 255).astype(np.uint8)
    return warped


def _append_boundary_line(
    target: list[np.ndarray],
    coordinates: object,
) -> None:
    array = np.asarray(coordinates, dtype=float)
    if (
        array.ndim != 2
        or array.shape[0] < 2
        or array.shape[1] < 2
        or not np.isfinite(array[:, :2]).all()
    ):
        return
    longitude = array[:, 0]
    latitude = array[:, 1]
    if (
        np.any(longitude < -180)
        or np.any(longitude > 180)
        or np.any(latitude < -90)
        or np.any(latitude > 90)
    ):
        raise ValueError("Boundary GeoJSON contains invalid coordinates")
    target.append(array[:, :2])


def _load_tile(
    *,
    layer: str,
    zoom: int,
    tile_x: int,
    tile_y: int,
    token: str,
    cache_directory: Path,
) -> Image.Image:
    path = (
        Path(cache_directory)
        / layer
        / str(zoom)
        / str(tile_x)
        / f"{tile_y}.png"
    )
    if path.exists():
        try:
            return Image.open(path).convert("RGBA")
        except OSError:
            path.unlink(missing_ok=True)
    url = build_tianditu_wmts_url(
        layer=layer,
        tile_matrix=zoom,
        tile_row=tile_y,
        tile_column=tile_x,
        token=token,
        server=(tile_x + tile_y) % 8,
    )
    try:
        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": (
                    "CloudyLakeObservatory/2.0 "
                    "(https://meteostation.top)"
                )
            },
        )
        response.raise_for_status()
        tile = Image.open(io.BytesIO(response.content)).convert("RGBA")
    except (requests.RequestException, OSError) as exc:
        raise TiandituBasemapUnavailable(
            f"Official map tile unavailable: {layer}/{zoom}/{tile_x}/{tile_y}"
        ) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    tile.save(path, format="PNG")
    return tile


def _longitude_to_tile_x(
    longitude: float | np.ndarray,
    zoom: int,
) -> float | np.ndarray:
    return (np.asarray(longitude) + 180.0) / 360.0 * (2**zoom)


def _latitude_to_tile_y(
    latitude: float | np.ndarray,
    zoom: int,
) -> float | np.ndarray:
    clipped = np.clip(np.asarray(latitude), -85.05112878, 85.05112878)
    radians = np.radians(clipped)
    return (
        1.0
        - np.log(np.tan(radians) + (1.0 / np.cos(radians))) / np.pi
    ) / 2.0 * (2**zoom)
