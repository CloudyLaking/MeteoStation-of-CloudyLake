"""Plan and retrieve source data for one China weather-map cycle."""

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from meteostation.weather_map import (
    EcmwfOpenDataUnavailable,
    EcmwfProductNotAvailable,
    HeightClimatologyUnavailable,
    NmcCycloneUnavailable,
    NrlCycloneUnavailable,
    TiandituBasemapUnavailable,
    WeatherMapCatalog,
    WeatherMapDecodeUnavailable,
    WeatherGrid,
    build_weather_map_plan,
    decode_ecmwf_background,
    fetch_nmc_tropical_cyclones,
    fetch_nrl_tropical_cyclones,
    load_tianditu_basemap,
    load_geojson_boundary,
    load_era5_height_climatology,
    load_era5_temperature_climatology,
    render_weather_map_preview,
    retrieve_ecmwf_input,
    retrieve_era5_height_climatology,
    retrieve_era5_temperature_climatology,
    update_preview_catalog,
)


PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan or retrieve ECMWF inputs for a China weather map."
    )
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--cycle", choices=["00", "12"], default="00")
    parser.add_argument(
        "--download",
        action="store_true",
        help="Retrieve the missing required ECMWF GRIB inputs.",
    )
    parser.add_argument(
        "--include-cyclone-tracks",
        action="store_true",
        help="Also retrieve the optional ECMWF tropical-cyclone BUFR track.",
    )
    parser.add_argument(
        "--download-climatology",
        action="store_true",
        help=(
            "Retrieve the ERA5 1991-2020 monthly 500 hPa height and "
            "850 hPa temperature normals used by anomaly layers."
        ),
    )
    parser.add_argument(
        "--render-preview",
        action="store_true",
        help=(
            "Decode archived ECMWF inputs and render field-only previews "
            "without administrative boundaries."
        ),
    )
    parser.add_argument(
        "--skip-cyclone-overlays",
        action="store_true",
        help="Do not refresh NRL ATCF cyclone positions while rendering.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_data_root = PROJECT_ROOT / "data" / "raw"
    catalog = WeatherMapCatalog(
        config_path=PROJECT_ROOT / "config" / "weather_map.json",
        catalog_path=(
            PROJECT_ROOT
            / "data"
            / "products"
            / "weather_maps"
            / "catalog.json"
        ),
    )
    plan = build_weather_map_plan(
        configuration=catalog.configuration(),
        valid_date=args.date,
        cycle=args.cycle,
        raw_data_root=raw_data_root,
    )
    configuration = catalog.configuration()
    height_climatology_configuration = configuration.climatology.get(
        "500_height",
        {},
    )
    if not isinstance(height_climatology_configuration, dict):
        height_climatology_configuration = {}
    path_template = str(
        height_climatology_configuration.get(
            "path_template",
            (
                "data/raw/era5_climatology/"
                "era5_500hpa_height_1991_2020_month_{month}.nc"
            ),
        )
    )
    height_climatology_path = PROJECT_ROOT / path_template.format(
        month=f"{args.date.month:02d}",
    )
    temperature_climatology_configuration = configuration.climatology.get(
        "850_temperature", {},
    )
    if not isinstance(temperature_climatology_configuration, dict):
        temperature_climatology_configuration = {}
    temperature_path_template = str(
        temperature_climatology_configuration.get(
            "path_template",
            "data/raw/era5_climatology/era5_850hpa_temperature_1991_2020_month_{month}.nc",
        )
    )
    temperature_climatology_path = PROJECT_ROOT / temperature_path_template.format(
        month=f"{args.date.month:02d}",
    )

    if args.download_climatology and not height_climatology_path.is_file():
        retrieved_path = retrieve_era5_height_climatology(
            height_climatology_path,
            pressure_hpa=500,
            start_year=1991,
            end_year=2020,
            month=args.date.month,
            west=configuration.domain.west,
            east=configuration.domain.east,
            south=configuration.domain.south,
            north=configuration.domain.north,
        )
        print(f"Archived 500 hPa height climatology: {retrieved_path}")
    if args.download_climatology and not temperature_climatology_path.is_file():
        retrieved_path = retrieve_era5_temperature_climatology(
            temperature_climatology_path,
            pressure_hpa=850,
            start_year=1991,
            end_year=2020,
            month=args.date.month,
            west=configuration.domain.west,
            east=configuration.domain.east,
            south=configuration.domain.south,
            north=configuration.domain.north,
        )
        print(f"Archived 850 hPa temperature climatology: {retrieved_path}")

    if args.download:
        for request in plan.requests:
            if request.status == "archived":
                continue
            if not request.required and not args.include_cyclone_tracks:
                continue
            try:
                path = retrieve_ecmwf_input(
                    request,
                    raw_data_root=raw_data_root,
                )
            except EcmwfProductNotAvailable:
                if request.required:
                    raise
                print(
                    "可选资料不可用："
                    f"{request.id}；本时次可能没有热带气旋轨迹。"
                )
                continue
            print(f"已归档：{path}")
        plan = build_weather_map_plan(
            configuration=catalog.configuration(),
            valid_date=args.date,
            cycle=args.cycle,
            raw_data_root=raw_data_root,
        )

    if args.render_preview:
        request_by_id = {
            request.id: request
            for request in plan.requests
        }
        missing = plan.missing_required_inputs
        if missing:
            raise SystemExit(
                "无法绘制：缺少 " + "、".join(missing)
            )
        grid = decode_ecmwf_background(
            surface_path=(
                raw_data_root
                / request_by_id["ecmwf-surface"].target_path
            ),
            pressure_path=(
                raw_data_root
                / request_by_id["ecmwf-pressure"].target_path
            ),
            valid_at=plan.valid_at,
            domain=configuration.domain,
            forecast_step_hours=(
                request_by_id["ecmwf-surface"].step_hours
            ),
            initialized_at=datetime(
                request_by_id["ecmwf-surface"].valid_date.year,
                request_by_id["ecmwf-surface"].valid_date.month,
                request_by_id["ecmwf-surface"].valid_date.day,
                int(request_by_id["ecmwf-surface"].cycle),
                tzinfo=timezone.utc,
            ),
        )
        height_climatology = load_era5_height_climatology(
            height_climatology_path,
            longitude=grid.longitude,
            latitude=grid.latitude,
            month=args.date.month,
            pressure_hpa=500,
            normal_period=str(
                height_climatology_configuration.get(
                    "normal_period",
                    "1991-2020",
                )
            ),
        )
        temperature_climatology = load_era5_temperature_climatology(
            temperature_climatology_path,
            longitude=grid.longitude,
            latitude=grid.latitude,
            month=args.date.month,
            pressure_hpa=850,
            normal_period=str(
                temperature_climatology_configuration.get("normal_period", "1991-2020")
            ),
        )
        grid = WeatherGrid(
            valid_at=grid.valid_at,
            source=grid.source,
            longitude=grid.longitude,
            latitude=grid.latitude,
            fields={
                **grid.fields,
                "geopotential_height_500_climatology_gpm": (
                    height_climatology.values_gpm
                ),
                "temperature_850_climatology_c": temperature_climatology.values_c,
            },
            metadata={
                **grid.metadata,
                "height_climatology_500": {
                    "source": height_climatology.source,
                    "normal_period": height_climatology.normal_period,
                    "month": height_climatology.month,
                    "path": height_climatology.path,
                },
                "temperature_climatology_850": {
                    "source": temperature_climatology.source,
                    "normal_period": temperature_climatology.normal_period,
                    "month": temperature_climatology.month,
                    "path": temperature_climatology.path,
                },
            },
        )
        base_map = None
        boundary_layer = None
        boundary_configuration = configuration.base_map.get(
            "local_boundary",
            {},
        )
        if isinstance(boundary_configuration, dict):
            boundary_path = PROJECT_ROOT / str(
                boundary_configuration.get("path", "")
            )
            if boundary_path.is_file():
                boundary_layer = load_geojson_boundary(
                    boundary_path,
                    source=str(
                        boundary_configuration.get(
                            "source",
                            "国家地理信息公共服务平台（天地图）",
                        )
                    ),
                )
        tianditu_token = os.environ.get("TIANDITU_TOKEN", "").strip()
        if tianditu_token:
            try:
                base_map = load_tianditu_basemap(
                    domain=configuration.domain,
                    token=tianditu_token,
                    cache_directory=(
                        PROJECT_ROOT / "data" / "cache" / "tianditu"
                    ),
                    source_review_number=str(
                        configuration.base_map.get(
                            "service_review_number",
                            "GS（2024）0568号",
                        )
                    ),
                )
            except TiandituBasemapUnavailable as exc:
                print(f"天地图官方底图暂不可用：{exc}")
        tropical_cyclones = []
        if not args.skip_cyclone_overlays:
            cyclone_archive_directory = (
                raw_data_root
                / "cyclones"
                / f"{plan.valid_at:%Y}"
                / f"{plan.valid_at:%m}"
                / f"{plan.valid_at:%d}"
                / f"{plan.valid_at:%H}"
            )
            try:
                tropical_cyclones.extend(fetch_nmc_tropical_cyclones(
                    valid_at=plan.valid_at,
                    domain=configuration.domain,
                    archive_directory=cyclone_archive_directory,
                ))
            except NmcCycloneUnavailable as exc:
                print(f"中央气象台热带气旋位置暂不可用：{exc}")
            try:
                nrl_markers = fetch_nrl_tropical_cyclones(
                    valid_at=plan.valid_at,
                    domain=configuration.domain,
                    archive_directory=cyclone_archive_directory,
                )
                existing_ids = {marker.id for marker in tropical_cyclones}
                tropical_cyclones.extend(
                    marker for marker in nrl_markers if marker.id not in existing_ids
                )
            except NrlCycloneUnavailable as exc:
                print(f"NRL 热带气旋备用源暂不可用：{exc}")
        preview_root = PROJECT_ROOT / "data" / "previews"
        previews = [
            render_weather_map_preview(
                grid,
                layer_id=layer,
                domain=configuration.domain,
                preview_root=preview_root,
                font_path=PROJECT_ROOT / "MiSans VF.ttf",
                cyclone_markers=tropical_cyclones,
                base_map=base_map,
                boundary_layer=boundary_layer,
            )
            for layer in ("composite", "surface", "850", "500", "200")
        ]
        update_preview_catalog(
            preview_root / "weather_maps" / "catalog.json",
            previews,
        )
        for preview in previews:
            print(f"开发预览：{preview.image_url}")

    print(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (
        EcmwfOpenDataUnavailable,
        HeightClimatologyUnavailable,
        WeatherMapDecodeUnavailable,
    ) as exc:
        raise SystemExit(str(exc)) from exc
