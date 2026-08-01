import json
import os
from datetime import datetime
from pathlib import Path

from .models import WeatherMapPreview


def update_preview_catalog(
    catalog_path: Path,
    previews: list[WeatherMapPreview],
) -> None:
    existing: dict[str, object] = {"previews": []}
    if Path(catalog_path).exists():
        try:
            existing = json.loads(
                Path(catalog_path).read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            pass
    serialized = [
        item
        for item in existing.get("previews", [])
        if isinstance(item, dict)
    ]
    replacement_keys = {
        _preview_key(preview.layer_id, preview.valid_at)
        for preview in previews
    }
    serialized = [
        item
        for item in serialized
        if _preview_key(item.get("layer_id"), item.get("valid_at"))
        not in replacement_keys
    ]
    serialized.extend(
        preview.model_dump(mode="json")
        for preview in previews
    )
    serialized.sort(
        key=lambda item: str(item.get("valid_at", "")),
        reverse=True,
    )
    payload = {"previews": serialized}
    path = Path(catalog_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _preview_key(
    layer_id: object,
    valid_at: object,
) -> tuple[str, str]:
    value = str(valid_at)
    try:
        normalized = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).isoformat()
    except ValueError:
        normalized = value
    return str(layer_id), normalized


def read_preview_catalog(catalog_path: Path) -> list[WeatherMapPreview]:
    if not Path(catalog_path).exists():
        return []
    try:
        payload = json.loads(
            Path(catalog_path).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return []
    return [
        WeatherMapPreview.model_validate(item)
        for item in payload.get("previews", [])
        if isinstance(item, dict)
    ]
