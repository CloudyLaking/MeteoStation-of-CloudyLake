import json
from datetime import date, datetime, timezone
from pathlib import Path

from .models import WeatherMapConfig, WeatherMapJob, WeatherMapProduct


class WeatherMapCatalog:
    def __init__(
        self,
        *,
        config_path: Path,
        catalog_path: Path,
    ) -> None:
        self.config_path = config_path
        self.catalog_path = catalog_path

    def configuration(self) -> WeatherMapConfig:
        payload = json.loads(
            self.config_path.read_text(encoding="utf-8")
        )
        station_file = payload.get("sounding_stations_file")
        if station_file:
            station_path = self.config_path.parent / str(station_file)
            station_payload = json.loads(
                station_path.read_text(encoding="utf-8")
            )
            local_overrides = {
                item["wmo_id"]: item
                for item in payload.get("sounding_stations", [])
                if isinstance(item, dict) and "wmo_id" in item
            }
            stations = []
            for item in station_payload.get("stations", []):
                if not isinstance(item, dict):
                    continue
                merged = {
                    **item,
                    **local_overrides.get(str(item.get("wmo_id")), {}),
                }
                stations.append(merged)
            payload["sounding_stations"] = stations
        return WeatherMapConfig.model_validate(payload)

    def products(
        self,
        *,
        valid_date: date,
        cycle: str,
        layer_id: str,
    ) -> list[WeatherMapProduct]:
        if not self.catalog_path.exists():
            return []
        try:
            payload = json.loads(
                self.catalog_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return []
        prefix = f"{valid_date.isoformat()}T{cycle}:"
        return [
            WeatherMapProduct.model_validate(item)
            for item in payload.get("products", [])
            if isinstance(item, dict)
            and item.get("layer_id") == layer_id
            and str(item.get("valid_at", "")).startswith(prefix)
        ]

    def latest_product(self, *, layer_id: str) -> WeatherMapProduct | None:
        """Return the newest complete product for a layer, if one exists."""
        if not self.catalog_path.exists():
            return None
        try:
            payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        products: list[WeatherMapProduct] = []
        for item in payload.get("products", []):
            if not isinstance(item, dict) or item.get("layer_id") != layer_id:
                continue
            try:
                products.append(WeatherMapProduct.model_validate(item))
            except ValueError:
                continue
        return max(products, key=lambda product: product.valid_at, default=None)

    def jobs(
        self,
        *,
        valid_date: date,
        cycle: str,
    ) -> list[WeatherMapJob]:
        configuration = self.configuration()
        valid_at = datetime(
            valid_date.year,
            valid_date.month,
            valid_date.day,
            int(cycle),
            tzinfo=timezone.utc,
        )
        jobs: list[WeatherMapJob] = []
        for layer in configuration.layers:
            archived = self.products(
                valid_date=valid_date,
                cycle=cycle,
                layer_id=layer.id,
            )
            blockers: list[str] = []
            if not archived:
                if not bool(
                    configuration.base_map.get(
                        "publication_allowed",
                        False,
                    )
                ):
                    blockers.append("compliant-base-map")
                blockers.append("ecmwf-input")
            jobs.append(
                WeatherMapJob(
                    layer_id=layer.id,
                    label=layer.label,
                    valid_at=valid_at,
                    status="complete" if archived else "waiting-input",
                    blockers=blockers,
                    recipe=layer.recipe,
                )
            )
        return jobs
