import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from meteostation.ecmwf_mars import (
    MarsAccessUnavailable,
    MarsClientUnavailable,
    retrieve_mars,
)

from .models import WeatherMapInputRequest


class EcmwfOpenDataUnavailable(RuntimeError):
    """Raised when the optional ECMWF retrieval dependency is unavailable."""


class EcmwfProductNotAvailable(RuntimeError):
    """Raised when an optional product does not exist for a model cycle."""


def retrieve_ecmwf_input(
    request: WeatherMapInputRequest,
    *,
    raw_data_root: Path,
    source: str = "ecmwf",
) -> Path:
    """Retrieve one planned ECMWF input atomically and record provenance."""
    backend = os.getenv("ECMWF_WEATHER_MAP_BACKEND", "auto").casefold()
    target = (Path(raw_data_root) / request.target_path).resolve()
    resolved_root = Path(raw_data_root).resolve()
    if target.parent != resolved_root and resolved_root not in target.parents:
        raise ValueError("ECMWF target escaped raw_data_root")
    if target.exists() and target.stat().st_size > 0:
        return target

    if backend in {"auto", "mars"}:
        try:
            return _retrieve_ecmwf_mars_input(
                request,
                target=target,
                backend_label="ECMWF MARS Web API",
            )
        except (MarsAccessUnavailable, MarsClientUnavailable):
            if backend == "mars":
                raise

    try:
        from ecmwf.opendata import Client
    except ImportError as exc:
        raise EcmwfOpenDataUnavailable(
            "缺少 ecmwf-opendata；请安装 requirements-weather-map.txt 后重试。"
        ) from exc

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    client = Client(
        source=source,
        model=request.model,
        resol=request.resolution,
        preserve_request_order=False,
        infer_stream_keyword=True,
    )
    retrieval: dict[str, object] = {
        "date": request.valid_date.isoformat(),
        "time": int(request.cycle),
        "stream": request.stream,
        "type": request.data_type,
        "step": request.step_hours,
    }
    if request.levtype:
        retrieval["levtype"] = request.levtype
    if request.levelist:
        retrieval["levelist"] = request.levelist
    if request.parameters:
        retrieval["param"] = request.parameters

    try:
        last_error: Exception | None = None
        for attempt in range(3):
            if temporary.exists():
                temporary.unlink()
            try:
                client.retrieve(request=retrieval, target=str(temporary))
                last_error = None
                break
            except Exception as exc:
                response = getattr(exc, "response", None)
                if getattr(response, "status_code", None) == 404:
                    raise EcmwfProductNotAvailable(
                        f"{request.id} is not available for "
                        f"{request.valid_date} {request.cycle} UTC"
                    ) from exc
                last_error = exc
                if attempt < 2:
                    time.sleep(4 * (attempt + 1))
        if last_error is not None:
            raise last_error
        if not temporary.exists() or temporary.stat().st_size == 0:
            raise RuntimeError("ECMWF retrieval returned an empty file")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()

    metadata = {
        "request": request.model_dump(mode="json"),
        "retrieval": retrieval,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source_endpoint": source,
        "license": "CC BY 4.0",
        "size_bytes": target.stat().st_size,
        "sha256": file_sha256(target),
    }
    metadata_path = target.with_suffix(target.suffix + ".json")
    metadata_temporary = metadata_path.with_suffix(
        metadata_path.suffix + ".tmp"
    )
    metadata_temporary.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(metadata_temporary, metadata_path)
    return target


def _retrieve_ecmwf_mars_input(
    request: WeatherMapInputRequest,
    *,
    target: Path,
    backend_label: str,
) -> Path:
    retrieval: dict[str, object] = {
        "class": "od",
        "expver": "1",
        "date": request.valid_date.isoformat(),
        "time": request.cycle,
        "stream": request.stream,
        "type": request.data_type,
        "step": str(request.step_hours),
    }
    if request.levtype:
        retrieval["levtype"] = request.levtype
    if request.levelist:
        retrieval["levelist"] = "/".join(
            str(level) for level in request.levelist
        )
    if request.parameters:
        retrieval["param"] = "/".join(request.parameters)
    if request.area and request.grid and request.data_type != "tf":
        retrieval["area"] = "/".join(str(value) for value in request.area)
        retrieval["grid"] = request.grid

    retrieve_mars(retrieval, target)
    metadata = {
        "request": request.model_dump(mode="json"),
        "retrieval": retrieval,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source_endpoint": backend_label,
        "license": "CC BY 4.0",
        "size_bytes": target.stat().st_size,
        "sha256": file_sha256(target),
    }
    metadata_path = target.with_suffix(target.suffix + ".json")
    metadata_temporary = metadata_path.with_suffix(
        metadata_path.suffix + ".tmp"
    )
    metadata_temporary.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(metadata_temporary, metadata_path)
    return target


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
