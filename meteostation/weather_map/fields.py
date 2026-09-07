from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from .models import WeatherMapDomain


@dataclass(frozen=True)
class WeatherGrid:
    """A normalized regular latitude/longitude weather field bundle."""

    valid_at: datetime
    source: str
    longitude: np.ndarray
    latitude: np.ndarray
    fields: dict[str, np.ndarray]
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        longitude = np.asarray(self.longitude, dtype=float)
        latitude = np.asarray(self.latitude, dtype=float)
        if longitude.ndim != 1 or latitude.ndim != 1:
            raise ValueError("Weather-grid coordinates must be one-dimensional")
        if longitude.size < 2 or latitude.size < 2:
            raise ValueError("Weather-grid coordinates are too short")
        expected_shape = (latitude.size, longitude.size)
        normalized_fields: dict[str, np.ndarray] = {}
        for name, values in self.fields.items():
            array = np.asarray(values, dtype=float).squeeze()
            if array.shape != expected_shape:
                raise ValueError(
                    f"Field {name!r} has shape {array.shape}; "
                    f"expected {expected_shape}"
                )
            normalized_fields[name] = array
        object.__setattr__(self, "longitude", longitude)
        object.__setattr__(self, "latitude", latitude)
        object.__setattr__(self, "fields", normalized_fields)

    def subset(self, domain: WeatherMapDomain) -> WeatherGrid:
        # Unwrap around the requested western edge, including dateline-crossing
        # regions such as 150E..210E. Never silently return half a global map.
        wrapped = (self.longitude - domain.west) % 360 + domain.west
        longitude_mask = (
            (wrapped >= domain.west)
            & (wrapped <= domain.east)
        )
        latitude_mask = (
            (self.latitude >= domain.south)
            & (self.latitude <= domain.north)
        )
        if longitude_mask.sum() < 2 or latitude_mask.sum() < 2:
            raise ValueError("Weather grid does not cover the configured domain")
        selected = np.flatnonzero(longitude_mask)
        selected = selected[np.argsort(wrapped[selected])]
        step = max(domain.resolution_degrees, float(np.median(np.diff(wrapped[selected]))))
        if (wrapped[selected][0] > domain.west + step * 1.1
            or wrapped[selected][-1] < domain.east - step * 1.1
            or np.max(np.diff(wrapped[selected])) > step * 1.5
            or self.latitude[latitude_mask].min() > domain.south + step * 1.1
            or self.latitude[latitude_mask].max() < domain.north - step * 1.1):
            raise ValueError("Weather grid does not cover the full requested domain")
        return WeatherGrid(
            valid_at=self.valid_at,
            source=self.source,
            longitude=wrapped[selected],
            latitude=self.latitude[latitude_mask],
            fields={
                name: values[np.ix_(latitude_mask, selected)]
                for name, values in self.fields.items()
            },
            metadata=self.metadata,
        )
