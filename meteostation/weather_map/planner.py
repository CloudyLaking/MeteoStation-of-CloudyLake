from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from .models import (
    WeatherMapConfig,
    WeatherMapInputRequest,
    WeatherMapPlan,
)


Cycle = Literal["00", "12"]


def build_weather_map_plan(
    *,
    configuration: WeatherMapConfig,
    valid_date: date,
    cycle: Cycle,
    raw_data_root: Path,
) -> WeatherMapPlan:
    """Build the immutable input plan for one 00/12 UTC analysis cycle."""
    if cycle not in configuration.cycles:
        raise ValueError(f"Unsupported weather-map cycle: {cycle}")

    pipeline = configuration.input_pipeline
    source = str(pipeline.get("source", "ECMWF Open Data"))
    model = str(pipeline.get("model", "ifs"))
    resolution = str(pipeline.get("resolution", "0p25"))
    stream = str(pipeline.get("stream", "oper"))
    data_type = str(pipeline.get("type", "fc"))
    step_hours = int(pipeline.get("step_hours", 0))
    valid_at = datetime(
        valid_date.year,
        valid_date.month,
        valid_date.day,
        int(cycle),
        tzinfo=timezone.utc,
    )
    initialization_at = valid_at - timedelta(hours=step_hours)
    initialization_date = initialization_at.date()
    initialization_cycle = f"{initialization_at.hour:02d}"
    archive_directory = (
        Path(raw_data_root)
        / "ecmwf"
        / f"{initialization_date:%Y}"
        / f"{initialization_date:%m}"
        / f"{initialization_date:%d}"
    )
    stem = (
        f"{model}_{initialization_date:%Y%m%d}_"
        f"{initialization_cycle}_step{step_hours:03d}"
    )

    specifications = [
        {
            "id": "ecmwf-surface",
            "format": "grib2",
            "levtype": "sfc",
            "parameters": ["msl", "sp", "2t", "10u", "10v", "tcwv"],
            "levelist": [],
            "area": [65.0, 65.0, 10.0, 150.0],
            "grid": "0.25/0.25",
            "target": archive_directory / f"{stem}_surface.grib2",
            "required": True,
            "purposes": ["composite", "surface"],
        },
        {
            "id": "ecmwf-pressure",
            "format": "grib2",
            "levtype": "pl",
            "parameters": ["gh", "t", "r", "u", "v", "vo", "d"],
            "levelist": [850, 500, 200],
            "area": [65.0, 65.0, 10.0, 150.0],
            "grid": "0.25/0.25",
            "target": archive_directory / f"{stem}_pressure.grib2",
            "required": True,
            "purposes": ["850", "500", "200"],
        },
        {
            "id": "ecmwf-tropical-cyclone-tracks",
            "format": "bufr",
            "levtype": None,
            "parameters": [],
            "levelist": [],
            "area": [],
            "grid": None,
            "target": (
                archive_directory
                / (
                    f"{model}_{initialization_date:%Y%m%d}_"
                    f"{initialization_cycle}"
                    "_step240_tropical-cyclones.bufr"
                )
            ),
            "required": False,
            "purposes": ["cyclone-overlay"],
            "data_type": "tf",
            "step_hours": 240,
        },
        {
            "id": "ecmwf-precipitation", "format": "grib2", "levtype": "sfc",
            "parameters": ["tp"], "levelist": [], "area": [], "grid": "0.25/0.25",
            "target": archive_directory / f"{stem}_precipitation.grib2",
            "required": False, "purposes": ["surface", "composite"],
        },
    ]

    requests: list[WeatherMapInputRequest] = []
    for item in specifications:
        target = Path(item["target"])
        requests.append(
            WeatherMapInputRequest(
                id=str(item["id"]),
                source=source,
                model=model,
                resolution=resolution,
                valid_date=initialization_date,
                cycle=initialization_cycle,
                stream=stream,
                data_type=str(item.get("data_type", data_type)),
                step_hours=int(item.get("step_hours", step_hours)),
                format=item["format"],
                levtype=item["levtype"],
                levelist=item["levelist"],
                parameters=item["parameters"],
                area=item["area"],
                grid=item["grid"],
                target_path=target.relative_to(raw_data_root).as_posix(),
                required=bool(item["required"]),
                purposes=item["purposes"],
                status="archived" if target.exists() else "missing",
            )
        )

    missing_required = [
        request.id
        for request in requests
        if request.required and request.status == "missing"
    ]
    blockers: list[str] = []
    if missing_required:
        blockers.append("ecmwf-input")
    if not bool(
        configuration.base_map.get(
            "publication_allowed",
            False,
        )
    ):
        blockers.append("compliant-base-map")

    if missing_required:
        status = "waiting-input"
    elif "compliant-base-map" in blockers:
        status = "waiting-compliant-base-map"
    else:
        status = "ready-for-analysis"

    return WeatherMapPlan(
        valid_at=valid_at,
        domain=configuration.domain,
        requests=requests,
        archived_inputs=sum(
            request.status == "archived" for request in requests
        ),
        missing_required_inputs=missing_required,
        blockers=blockers,
        status=status,
    )
