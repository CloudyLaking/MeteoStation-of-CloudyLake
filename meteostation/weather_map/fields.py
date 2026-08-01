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
        longitude_mask = (
            (self.longitude >= domain.west)
            & (self.longitude <= domain.east)
        )
        latitude_mask = (
            (self.latitude >= domain.south)
            & (self.latitude <= domain.north)
        )
        if longitude_mask.sum() < 2 or latitude_mask.sum() < 2:
            raise ValueError("Weather grid does not cover the configured domain")
        return WeatherGrid(
            valid_at=self.valid_at,
            source=self.source,
            longitude=self.longitude[longitude_mask],
            latitude=self.latitude[latitude_mask],
            fields={
                name: values[np.ix_(latitude_mask, longitude_mask)]
                for name, values in self.fields.items()
            },
            metadata=self.metadata,
        )
