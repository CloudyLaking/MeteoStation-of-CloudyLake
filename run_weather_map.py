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
    JtwcCycloneUnavailable,
    NrlCycloneUnavailable,
    TiandituBasemapUnavailable,
    WeatherMapCatalog,
    WeatherMapDecodeUnavailable,
    WeatherGrid,
    build_weather_map_plan,
    decode_ecmwf_background,
    fetch_jtwc_tropical_cyclones,
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
        help="Do not refresh JTWC ATCF cyclone positions while rendering.",
    )
    parser.add_argument("--region", default="china", help="Output scope: china, world, or a safe region name with --bounds")
    parser.add_argument("--bounds", type=float, nargs=4, metavar=("WEST","SOUTH","EAST","NORTH"))
    parser.add_argument("--preview-root", type=Path, help="Optional isolated preview output directory for visual review")
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
    from meteostation.weather_map.regions import region_domain
    requested_domain = region_domain(args.region, args.bounds, configuration.domain)
    configuration = configuration.model_copy(update={"domain":requested_domain,"region":args.region})
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
            if not request.required and request.id != "ecmwf-precipitation" and not args.include_cyclone_tracks:
                continue
            try:
                path = retrieve_ecmwf_input(
                    request,
                    raw_data_root=raw_data_root,
                )
            except Exception:
                if request.required:
                    raise
                print(
                    "可选资料不可用："
                    f"{request.id}；继续绘制已核验的字段，不补造缺失资料。"
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
            precipitation_path=raw_data_root / request_by_id["ecmwf-precipitation"].target_path,
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
        if 70 <= requested_domain.west < requested_domain.east <= 145 and 15 <= requested_domain.south < requested_domain.north <= 60:
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
        if args.region == "world":
            grid = WeatherGrid(valid_at=grid.valid_at,source=grid.source,
                longitude=grid.longitude[::4],latitude=grid.latitude[::4],
                fields={k:v[::4,::4] for k,v in grid.fields.items()},metadata=grid.metadata)
        base_map = None
        boundary_layer = None
        boundary_configuration = configuration.base_map.get(
            "local_boundary",
            {},
        )
        if args.region != "world" and isinstance(boundary_configuration, dict):
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
        if tianditu_token and args.region == "china":
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
                tropical_cyclones.extend(fetch_jtwc_tropical_cyclones(
                    valid_at=plan.valid_at,
                    domain=configuration.domain,
                    archive_directory=cyclone_archive_directory,
                ))
            except JtwcCycloneUnavailable as exc:
                print(f"JTWC 热带气旋资料暂不可用：{exc}")
            if not tropical_cyclones:
                try:
                    tropical_cyclones.extend(fetch_nrl_tropical_cyclones(
                        valid_at=plan.valid_at,
                        domain=configuration.domain,
                        archive_directory=cyclone_archive_directory,
                    ))
                except NrlCycloneUnavailable as exc:
                    print(f"JTWC/NRL 备用资料暂不可用：{exc}")
        preview_root = args.preview_root or PROJECT_ROOT / "data" / "previews"
        if args.region != "china":
            preview_root = preview_root / "regions" / args.region
        preview_root.mkdir(parents=True, exist_ok=True)
        if args.region != "china":
            regional_layers = []
            for layer in configuration.layers:
                if (layer.id == "composite"
                    and "temperature_850_climatology_c" not in grid.fields):
                    layer = layer.model_copy(update={
                        "description":"850 hPa 实际温度填色、850 hPa 风场与 500 hPa 位势高度等值线",
                        "recipe":{"fields":["850_temperature","850_wind","500_geopotential_height"]},
                    })
                elif (layer.id == "500"
                      and "geopotential_height_500_climatology_gpm" not in grid.fields):
                    layer = layer.model_copy(update={
                        "description":"500 hPa 相对湿度、位势高度等值线与风场",
                        "recipe":{"pressure_hpa":500,"fields":["relative_humidity","geopotential","wind"]},
                    })
                regional_layers.append(layer)
            configuration=configuration.model_copy(update={"layers":regional_layers,"sounding_stations":[],"base_map":{
                **configuration.base_map,"source":"Natural Earth 海岸线；中国境界沿用天地图资料",
                "service_review_number":None}})
            region_path=preview_root / "region.json"
            temporary_region=region_path.with_suffix('.json.tmp')
            temporary_region.write_text(json.dumps(configuration.model_dump(mode="json"),ensure_ascii=False),encoding="utf8")
            os.replace(temporary_region,region_path)
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
        if args.region != "china":
            previews = [p.model_copy(update={"image_url":p.image_url.replace("/previews/",f"/previews/regions/{args.region}/",1), "metadata_url":p.metadata_url.replace("/previews/",f"/previews/regions/{args.region}/",1)}) for p in previews]
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
