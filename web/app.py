import asyncio
import io
import json
import os
import re
import secrets
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from meteostation.operations import (
    AdminAction,
    RuntimeTraffic,
    SiteConfig,
    load_site_config,
    operations_snapshot,
    request_admin_action,
    save_site_config,
    server_congestion_snapshot,
)
from meteostation.observation import (
    QWeatherError,
    RealtimeObservation,
    StationLookupError,
    fetch_qweather_hourly,
    fetch_qweather_realtime,
    render_legacy_observation_png,
    resolve_station,
    search_stations,
)
from meteostation.sounding import (
    CorrectedSounding,
    SoundingDiagnostics,
    SoundingCorrectionInput,
    SoundingLevel,
    SoundingProfile,
    WyomingSoundingClient,
    apply_surface_correction,
    calculate_sounding_diagnostics,
)
from meteostation.sounding.wyoming import (
    WyomingSoundingNotFound,
    validate_station_id,
)
from meteostation.weather_map import (
    WeatherMapCatalog,
    WeatherMapConfig,
    WeatherMapPlan,
    build_weather_map_plan,
    read_preview_catalog,
)
from meteostation.forecast import (
    extract_sounding_forecast,
    extract_surface_forecast,
    retrieve_ecmwf_forecast,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "web" / "static"
BRAND_DIR = PROJECT_ROOT / "assets" / "brand"
FONT_FILE = PROJECT_ROOT / "MiSans VF.ttf"
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PRODUCT_DATA_DIR = PROJECT_ROOT / "data" / "products"
PREVIEW_DATA_DIR = PROJECT_ROOT / "data" / "previews"
COLLECTOR_STATE_PATH = (
    PROJECT_ROOT / "data" / "state" / "sounding_collector.json"
)
FORECAST_COLLECTOR_STATE_PATH = (
    PROJECT_ROOT / "data" / "state" / "forecast_collector.json"
)
SOUNDING_CATALOG_PATH = PRODUCT_DATA_DIR / "soundings" / "catalog.json"
WEATHER_MAP_CONFIG_PATH = PROJECT_ROOT / "config" / "weather_map.json"
WEATHER_MAP_CATALOG_PATH = PRODUCT_DATA_DIR / "weather_maps" / "catalog.json"
WEATHER_MAP_PREVIEW_CATALOG_PATH = (
    PREVIEW_DATA_DIR / "weather_maps" / "catalog.json"
)
SITE_CONFIG_PATH = PROJECT_ROOT / "config" / "site.json"
TRAFFIC_STATE_PATH = PROJECT_ROOT / "data" / "state" / "traffic.json"
GUESTBOOK_STATE_PATH = PROJECT_ROOT / "data" / "state" / "guestbook.json"

wyoming_client = WyomingSoundingClient(cache_root=RAW_DATA_DIR)
weather_map_catalog = WeatherMapCatalog(
    config_path=WEATHER_MAP_CONFIG_PATH,
    catalog_path=WEATHER_MAP_CATALOG_PATH,
)
observation_plot_lock = asyncio.Lock()
guestbook_lock = asyncio.Lock()
traffic = RuntimeTraffic(TRAFFIC_STATE_PATH)
admin_security = HTTPBasic(auto_error=False)
PRODUCT_DATA_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_DATA_DIR.mkdir(parents=True, exist_ok=True)


app = FastAPI(
    title="云海观象台 API",
    description="CloudyLake's Observatory 网站与气象数据服务。Powered with Codex & Deepseek V4 Pro.",
    version="2.1.1",
)


@app.middleware("http")
async def count_application_traffic(request: Request, call_next):
    response = await call_next(request)
    try:
        response_bytes = int(response.headers.get("content-length", "0"))
    except ValueError:
        response_bytes = 0
    traffic.record(request.url.path, response.status_code, response_bytes)
    return response


@app.get("/", include_in_schema=False)
async def homepage() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/observations", include_in_schema=False)
async def observations_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "observations.html")


@app.get("/forecast", include_in_schema=False)
async def forecast_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "forecast.html")


@app.get("/sounding-forecast", include_in_schema=False)
async def sounding_forecast_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "sounding-forecast.html")


@app.get("/about", include_in_schema=False)
async def about_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "about.html")


class GuestbookSubmission(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    message: str = Field(min_length=2, max_length=500)

    @field_validator("name", "message")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("内容不能为空")
        return normalized


@app.get("/static/fonts/MiSans-VF.ttf", include_in_schema=False)
async def misans_font() -> FileResponse:
    return FileResponse(FONT_FILE, media_type="font/ttf")


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "CloudyLake's Observatory"}


@app.get("/api/v1/status")
async def project_status() -> dict[str, object]:
    return {
        "version": "V2.1.1",
        "stage": "china-weather-map-input-pipeline",
        "updated_at": "2026-08-01",
        "archive_policy": "soundings-saved-surface-query-no-store",
        "modules": [
            {
                "id": "china-map",
                "label": "中国天气主页",
                "status": "automatic-analysis-running",
            },
            {"id": "historical-reanalysis", "label": "历史再分析", "status": "planned"},
            {"id": "aifs-ens", "label": "AIFS ENS预报", "status": "planned"},
            {
                "id": "sounding",
                "label": "交互式探空图",
                "status": "professional-interactive",
            },
            {
                "id": "sounding-collector",
                "label": "自动探空采集器",
                "status": "implemented",
            },
            {
                "id": "surface-obs",
                "label": "气象站静态实况查询",
                "status": "on-demand-static",
            },
            {"id": "point-forecast", "label": "单点预报", "status": "implemented"},
            {"id": "sounding-forecast", "label": "探空预报", "status": "implemented"},
            {
                "id": "forecast-collector",
                "label": "IFS/AIFS预报更新监测器",
                "status": "implemented",
            },
            {
                "id": "operations-monitor",
                "label": "私有运维监视器",
                "status": "implemented",
            },
        ],
        "sources": [
            {
                "id": "wyoming",
                "label": "Wyoming 探空",
                "role": "primary",
                "url": "https://weather.uwyo.edu/upperair/sounding.html",
            },
            {
                "id": "metar",
                "label": "Aviation Weather METAR",
                "role": "supplement",
                "url": "https://aviationweather.gov/data/api/",
            },
            {
                "id": "q-weather",
                "label": "q-weather 逐小时 / 实时",
                "role": "primary-v1",
                "url": "https://q-weather.info/",
            },
            {
                "id": "wis2",
                "label": "WMO WIS 2.0",
                "role": "realtime",
                "url": "https://community.wmo.int/en/activity-areas/wis/wis2-overview",
            },
            {
                "id": "ecmwf-open-data",
                "label": "ECMWF Open Data",
                "role": "background",
                "url": "https://www.ecmwf.int/en/forecasts/datasets/open-data",
            },
        ],
    }


def require_admin(
    credentials: HTTPBasicCredentials | None = Depends(admin_security),
) -> str:
    expected_user = os.environ.get("METEOSTATION_ADMIN_USER", "").strip()
    expected_password = os.environ.get("METEOSTATION_ADMIN_PASSWORD", "")
    valid = (
        credentials is not None
        and bool(expected_user)
        and bool(expected_password)
        and secrets.compare_digest(credentials.username, expected_user)
        and secrets.compare_digest(credentials.password, expected_password)
    )
    if not valid:
        raise HTTPException(
            status_code=401,
            detail="需要运维后台身份验证",
            headers={"WWW-Authenticate": 'Basic realm="CloudyLake Operations"'},
        )
    return credentials.username


def require_admin_confirmation(
    confirmation: str = Header(default="", alias="X-Admin-Action"),
) -> None:
    if not secrets.compare_digest(confirmation, "confirm"):
        raise HTTPException(status_code=403, detail="缺少运维动作确认标头")


@app.get("/admin", include_in_schema=False)
async def admin_page(_: str = Depends(require_admin)) -> FileResponse:
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/api/v1/site/config")
async def public_site_config() -> dict[str, object]:
    return load_site_config(SITE_CONFIG_PATH).model_dump(mode="json")


@app.get("/api/v1/site/stats")
async def public_site_stats() -> dict[str, object]:
    return {
        **traffic.snapshot(),
        "congestion": server_congestion_snapshot(PROJECT_ROOT),
    }


@app.post("/api/v1/mailbox", status_code=202)
async def submit_mailbox_entry(
    submission: GuestbookSubmission,
) -> dict[str, object]:
    async with guestbook_lock:
        state = read_json(GUESTBOOK_STATE_PATH, default={"entries": []})
        entries = state.get("entries", [])
        if not isinstance(entries, list):
            entries = []
        entry = {
            "id": secrets.token_hex(8),
            "name": submission.name,
            "message": submission.message,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }
        # Keep a bounded private inbox and preserve archived entries. No
        # unauthenticated read endpoint is intentionally provided.
        pending = [
            item
            for item in entries
            if isinstance(item, dict) and item.get("status") == "pending"
        ][-199:]
        approved = [
            item
            for item in entries
            if isinstance(item, dict) and item.get("status") == "approved"
        ][-199:]
        write_json_atomic(
            GUESTBOOK_STATE_PATH,
            {"entries": [*approved, *pending, entry]},
        )
    return {"accepted": True, "detail": "来信已投递，仅站长可见。"}


@app.get("/api/v1/admin/status")
async def admin_status(_: str = Depends(require_admin)) -> dict[str, object]:
    guestbook = read_json(GUESTBOOK_STATE_PATH, default={"entries": []})
    guestbook_entries = guestbook.get("entries", [])
    if not isinstance(guestbook_entries, list):
        guestbook_entries = []
    return {
        **operations_snapshot(PROJECT_ROOT),
        "traffic": traffic.snapshot(),
        "site": load_site_config(SITE_CONFIG_PATH).model_dump(mode="json"),
        "mailbox": {
            "unread": [
                item
                for item in guestbook_entries
                if isinstance(item, dict) and item.get("status") == "pending"
            ][::-1],
        },
    }


@app.post("/api/v1/admin/mailbox/{entry_id}/archive")
async def archive_mailbox_entry(
    entry_id: str,
    _: str = Depends(require_admin),
    __: None = Depends(require_admin_confirmation),
) -> dict[str, object]:
    return await moderate_guestbook(entry_id, "approved")


@app.delete("/api/v1/admin/mailbox/{entry_id}")
async def delete_mailbox_entry(
    entry_id: str,
    _: str = Depends(require_admin),
    __: None = Depends(require_admin_confirmation),
) -> dict[str, object]:
    return await moderate_guestbook(entry_id, "deleted")


@app.put("/api/v1/admin/site")
async def update_site_configuration(
    configuration: SiteConfig,
    _: str = Depends(require_admin),
    __: None = Depends(require_admin_confirmation),
) -> dict[str, object]:
    save_site_config(SITE_CONFIG_PATH, configuration)
    return {
        "saved": True,
        "site": configuration.model_dump(mode="json"),
    }


@app.post("/api/v1/admin/refresh/{action}")
async def refresh_data_pipeline(
    action: AdminAction,
    _: str = Depends(require_admin),
    __: None = Depends(require_admin_confirmation),
) -> dict[str, object]:
    result = await asyncio.to_thread(request_admin_action, action)
    if not result["accepted"]:
        raise HTTPException(status_code=503, detail=result["detail"])
    return result


@app.get(
    "/api/v1/weather-maps/config",
    response_model=WeatherMapConfig,
    summary="读取中国天气图图层、时次和底图接入状态",
)
async def weather_map_configuration() -> WeatherMapConfig:
    configuration = weather_map_catalog.configuration()
    base_map = dict(configuration.base_map)
    token_variable = str(
        base_map.get(
            "token_environment_variable",
            "TIANDITU_TOKEN",
        )
    )
    base_map["token_configured"] = bool(
        os.environ.get(token_variable, "").strip()
    )
    return configuration.model_copy(update={"base_map": base_map})


@app.get(
    "/api/v1/weather-maps/plan",
    response_model=WeatherMapPlan,
    summary="读取指定 00/12 UTC 中国天气图的 ECMWF 输入计划",
)
async def weather_map_plan(
    valid_date: date = Query(alias="date"),
    cycle: Literal["00", "12"] = Query(default="00"),
) -> WeatherMapPlan:
    return build_weather_map_plan(
        configuration=weather_map_catalog.configuration(),
        valid_date=valid_date,
        cycle=cycle,
        raw_data_root=RAW_DATA_DIR,
    )


@app.get(
    "/api/v1/weather-maps/previews",
    summary="读取天气场开发预览",
)
async def weather_map_previews(
    valid_date: date = Query(alias="date"),
    cycle: Literal["00", "12"] = Query(default="00"),
    layer: str | None = Query(default=None, max_length=40),
) -> dict[str, object]:
    target_prefix = f"{valid_date.isoformat()}T{cycle}:"
    previews = [
        preview
        for preview in read_preview_catalog(
            WEATHER_MAP_PREVIEW_CATALOG_PATH
        )
        if preview.valid_at.isoformat().startswith(target_prefix)
        and (layer is None or preview.layer_id == layer)
    ]
    has_official_boundaries = any(
        preview.base_map_status == "official-boundary-preview"
        for preview in previews
    )
    return {
        "date": valid_date,
        "cycle": cycle,
        "layer": layer,
        "warning": (
            "TIANDITU BOUNDARY DATA"
            if has_official_boundaries
            else "ECMWF FIELD · NO ADMINISTRATIVE BOUNDARIES"
        ),
        "previews": [
            preview.model_dump(mode="json")
            for preview in previews
        ],
    }


@app.get(
    "/api/v1/weather-maps/products",
    summary="按日期、时次和图层读取已保存天气图",
)
async def weather_map_products(
    valid_date: date = Query(alias="date"),
    cycle: Literal["00", "12"] = Query(default="00"),
    layer: str = Query(default="composite", min_length=1, max_length=40),
) -> dict[str, object]:
    configuration = weather_map_catalog.configuration()
    known_layers = {item.id for item in configuration.layers}
    if layer not in known_layers:
        raise HTTPException(status_code=422, detail="unknown weather-map layer")
    products = weather_map_catalog.products(
        valid_date=valid_date,
        cycle=cycle,
        layer_id=layer,
    )
    job = next(
        item
        for item in weather_map_catalog.jobs(
            valid_date=valid_date,
            cycle=cycle,
        )
        if item.layer_id == layer
    )
    input_plan = build_weather_map_plan(
        configuration=configuration,
        valid_date=valid_date,
        cycle=cycle,
        raw_data_root=RAW_DATA_DIR,
    )
    return {
        "date": valid_date,
        "cycle": cycle,
        "layer": layer,
        "products": [product.model_dump(mode="json") for product in products],
        "job": job.model_dump(mode="json"),
        "input_plan": {
            "status": input_plan.status,
            "archived_inputs": input_plan.archived_inputs,
            "missing_required_inputs": input_plan.missing_required_inputs,
        },
        "base_map": configuration.base_map,
    }


@app.get(
    "/api/v1/weather-maps/sounding-stations",
    summary="读取中国天气图探空站及本地归档状态",
)
async def weather_map_sounding_stations(
    sounding_date: date = Query(alias="date"),
    cycle: Literal["00", "12"] = Query(default="00"),
) -> dict[str, object]:
    profiles: list[dict[str, object]] = []
    configuration = weather_map_catalog.configuration()
    for station in configuration.sounding_stations:
        try:
            profile = wyoming_client.load_cached_profile(
                station_id=station.wmo_id,
                sounding_date=sounding_date,
                cycle=cycle,
            )
        except WyomingSoundingNotFound:
            continue
        profiles.append(
            {
                "wmo_id": station.wmo_id,
                "profile": profile.model_dump(mode="json"),
            }
        )
    return {
        "date": sounding_date,
        "cycle": cycle,
        "station_count": len(configuration.sounding_stations),
        "updated_count": len(profiles),
        "profiles": profiles,
    }


@app.get(
    "/api/v1/weather-maps/jobs",
    summary="生成指定 00/12 UTC 时次的天气图任务与阻塞状态",
)
async def weather_map_jobs(
    valid_date: date = Query(alias="date"),
    cycle: Literal["00", "12"] = Query(default="00"),
) -> dict[str, object]:
    jobs = weather_map_catalog.jobs(
        valid_date=valid_date,
        cycle=cycle,
    )
    return {
        "date": valid_date,
        "cycle": cycle,
        "jobs": [job.model_dump(mode="json") for job in jobs],
    }


@app.get(
    "/api/v1/stations/search",
    summary="按 WMO 站号或中文站名检索内置气象站表",
)
async def station_search(
    q: str = Query(min_length=1, max_length=40),
    limit: int = Query(default=8, ge=1, le=20),
) -> dict[str, object]:
    return {
        "query": q,
        "stations": [
            station.as_dict()
            for station in search_stations(q, limit=limit)
        ],
    }


@app.get(
    "/api/v1/stations/resolve",
    summary="将 WMO 站号或中文站名解析为唯一站点",
)
async def station_resolve(
    q: str = Query(min_length=1, max_length=40),
) -> dict[str, object]:
    try:
        return resolve_station(q).as_dict()
    except StationLookupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/api/v1/observations/realtime/{station_id}",
    response_model=RealtimeObservation,
    summary="读取 q-weather 气象站实时状态",
)
async def realtime_observation(station_id: str) -> RealtimeObservation:
    validate_station_id(station_id)
    try:
        resolve_station(station_id)
        return await fetch_qweather_realtime(station_id)
    except StationLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QWeatherError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get(
    "/api/v1/observations/hourly/{station_id}",
    response_model=RealtimeObservation,
    summary="读取指定整点的 q-weather 逐小时地面资料",
)
async def hourly_observation(
    station_id: str,
    observed_at: datetime = Query(alias="time"),
) -> RealtimeObservation:
    validate_station_id(station_id)
    if (
        observed_at.minute != 0
        or observed_at.second != 0
        or observed_at.microsecond != 0
    ):
        raise HTTPException(status_code=422, detail="time must be on the hour")
    try:
        resolve_station(station_id)
        return await fetch_qweather_hourly(station_id, observed_at)
    except StationLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QWeatherError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get(
    "/api/v1/observations/plot",
    summary="调用原 q-weather 逐小时数据源生成地面实况静态图",
)
async def surface_observation_plot(
    station_query: str = Query(alias="station", min_length=1, max_length=40),
    mode: Literal["past24h", "history"] = Query(default="past24h"),
    historical_date: date | None = Query(default=None, alias="date"),
) -> StreamingResponse:
    if historical_date is not None and historical_date > datetime.now(
        timezone.utc
    ).date():
        raise HTTPException(status_code=422, detail="date cannot be in the future")
    if mode == "history" and historical_date is None:
        raise HTTPException(
            status_code=422,
            detail="history mode requires date",
        )

    try:
        station = resolve_station(station_query)
    except StationLookupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    date_label = (
        "today"
        if mode == "past24h"
        else historical_date.strftime("%Y%m%d")
    )
    async with observation_plot_lock:
        try:
            result = await asyncio.to_thread(
                render_legacy_observation_png,
                station=station,
                mode=mode,
                historical_date=historical_date,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"静态实况图生成失败：{exc}",
            ) from exc
    filename = (
        f"{station.wmo_id}_{date_label.replace(' ', '-')}_observations.png"
    )
    return StreamingResponse(
        io.BytesIO(result.image_bytes),
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-Observation-Source": "Q-WEATHER-HOURLY",
            "X-Observation-Source-URL": result.source_url,
            "X-Observation-Station": station.wmo_id,
            "X-Observation-Count": str(result.observation_count),
        },
    )


@app.get(
    "/api/v1/soundings/{station_id}",
    response_model=SoundingProfile,
    summary="从本地归档读取一个探空廓线",
)
async def sounding_profile(
    station_id: str,
    sounding_date: date = Query(alias="date"),
    cycle: Literal["00", "12"] = Query(default="00"),
) -> SoundingProfile:
    if len(station_id) != 5 or not station_id.isdigit():
        raise HTTPException(
            status_code=422,
            detail="station_id must be a five-digit WMO station number",
        )
    if sounding_date > datetime.now(timezone.utc).date():
        raise HTTPException(
            status_code=422,
            detail="date cannot be in the future",
        )

    try:
        return wyoming_client.load_cached_profile(
            station_id=station_id,
            sounding_date=sounding_date,
            cycle=cycle,
        )
    except WyomingSoundingNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/soundings/{station_id}/raw")
async def raw_sounding(
    station_id: str,
    sounding_date: date = Query(alias="date"),
    cycle: Literal["00", "12"] = Query(default="00"),
) -> FileResponse:
    try:
        csv_path, _ = wyoming_client.cached_paths(
            station_id=station_id,
            sounding_date=sounding_date,
            cycle=cycle,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="Raw sounding is not archived")
    return FileResponse(
        csv_path,
        media_type="text/csv; charset=utf-8",
        filename=f"{station_id}_{sounding_date.isoformat()}_{cycle}UTC.csv",
    )


@app.get(
    "/api/v1/soundings/{station_id}/diagnostics",
    response_model=SoundingDiagnostics,
    summary="计算本地探空的热力诊断量",
)
async def sounding_diagnostics(
    station_id: str,
    sounding_date: date = Query(alias="date"),
    cycle: Literal["00", "12"] = Query(default="00"),
) -> SoundingDiagnostics:
    profile = await sounding_profile(
        station_id=station_id,
        sounding_date=sounding_date,
        cycle=cycle,
    )
    try:
        return calculate_sounding_diagnostics(profile)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    "/api/v1/soundings/{station_id}/correct",
    response_model=CorrectedSounding,
    summary="用地面气压、温度和露点对探空廓线作非破坏性订正",
)
async def correct_sounding(
    correction: SoundingCorrectionInput,
    station_id: str,
    sounding_date: date = Query(alias="date"),
    cycle: Literal["00", "12"] = Query(default="00"),
) -> CorrectedSounding:
    profile = await sounding_profile(
        station_id=station_id,
        sounding_date=sounding_date,
        cycle=cycle,
    )
    try:
        corrected_profile = apply_surface_correction(profile, correction)
        diagnostics = calculate_sounding_diagnostics(corrected_profile)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CorrectedSounding(
        profile=corrected_profile,
        diagnostics=diagnostics,
        correction=correction,
    )


@app.get("/api/v1/collector/status")
async def collector_status() -> dict[str, object]:
    return read_json(
        COLLECTOR_STATE_PATH,
        default={"status": "never-run", "items": {}},
    )


@app.get("/api/v1/products/soundings")
async def sounding_products() -> dict[str, object]:
    return read_json(
        SOUNDING_CATALOG_PATH,
        default={"updated_at": None, "products": []},
    )


@app.get("/api/v1/products/soundings/{station_id}")
async def sounding_product(
    station_id: str,
    sounding_date: date = Query(alias="date"),
    cycle: Literal["00", "12"] = Query(default="00"),
    diagram: Literal["skewt", "stuve"] = Query(default="skewt"),
) -> dict[str, object]:
    catalog = read_json(
        SOUNDING_CATALOG_PATH,
        default={"updated_at": None, "products": []},
    )
    target_prefix = f"{sounding_date.isoformat()}T{cycle}:00:00"
    for product in catalog.get("products", []):
        if not isinstance(product, dict):
            continue
        if product.get("station_id") == station_id and str(
            product.get("valid_at", "")
        ).startswith(target_prefix) and product.get("diagram_type") == diagram:
            return product
    raise HTTPException(status_code=404, detail="Sounding image is not archived")


def read_json(path: Path, *, default: dict[str, object]) -> dict[str, object]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


async def moderate_guestbook(
    entry_id: str,
    target_status: Literal["approved", "deleted"],
) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{16}", entry_id):
        raise HTTPException(status_code=422, detail="来信编号无效")
    async with guestbook_lock:
        state = read_json(GUESTBOOK_STATE_PATH, default={"entries": []})
        entries = state.get("entries", [])
        if not isinstance(entries, list):
            entries = []
        found = False
        updated: list[dict[str, object]] = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            if item.get("id") == entry_id:
                found = True
                if target_status == "deleted":
                    continue
                item = {**item, "status": "approved"}
            updated.append(item)
        if not found:
            raise HTTPException(status_code=404, detail="来信不存在")
        write_json_atomic(GUESTBOOK_STATE_PATH, {"entries": updated})
    return {"updated": True, "id": entry_id, "status": target_status}


# ---------------------------------------------------------------------------
# Forecast API
# ---------------------------------------------------------------------------

FORECAST_CACHE_ROOT = PROJECT_ROOT / "data" / "raw"
FORECAST_CYCLES = ("00", "06", "12", "18")
FORECAST_MODELS = ("ifs", "aifs")


@app.get("/api/v1/forecast/cache/status")
async def forecast_cache_status() -> dict[str, object]:
    """Return the forecast-cycle monitor state without starting downloads."""
    return read_json(
        FORECAST_COLLECTOR_STATE_PATH,
        default={
            "updated_at": None,
            "items": {},
            "last_run": None,
        },
    )


@app.get("/api/v1/forecast/surface/{location}")
async def surface_forecast(
    location: str,
    date: date | None = None,
    cycle: str = Query(default="00", pattern=r"^(00|06|12|18)$"),
    model: str = Query(default="ifs", pattern=r"^(ifs|aifs)$"),
    target: datetime | None = Query(default=None, alias="target"),
    horizon: int = Query(default=72, ge=3, le=144),
) -> dict[str, object]:
    """ECMWF surface point forecast for one station.

    *target* is an ISO-8601 datetime; when given, only the matching
    forecast step is returned instead of the full time series.
    """
    try:
        point = resolve_forecast_location(location)
    except StationLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    initialized_at = _build_initialized_at(date, cycle)

    try:
        surf_path, _ = await asyncio.to_thread(
            retrieve_ecmwf_forecast,
            initialized_at=initialized_at,
            cache_root=FORECAST_CACHE_ROOT,
            model=model,
            include_pressure=False,
            latitude=point["latitude"],
            longitude=point["longitude"],
            backend="open-data",
            allow_download=False,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"ECMWF {model.upper()} forecast unavailable: {exc}",
        )

    forecast = await asyncio.to_thread(
        extract_surface_forecast,
        surf_path,
        station_id=point["id"],
        station_name=point["name"],
        latitude=point["latitude"],
        longitude=point["longitude"],
        initialized_at=initialized_at,
    )
    if forecast is None:
        raise HTTPException(status_code=422, detail="Could not decode forecast")
    forecast = forecast.model_copy(
        update={
            "points": [
                point
                for point in forecast.points
                if 0 < point.step_hours <= horizon
            ]
        }
    )
    if target is not None:
        matches = [p for p in forecast.points if p.valid_at == target]
        if not matches:
            raise HTTPException(status_code=404, detail=f"No forecast at {target}")
        forecast = forecast.model_copy(update={"points": matches})
    return forecast.model_dump(mode="json")


@app.get("/api/v1/forecast/sounding/{location}")
async def sounding_forecast(
    location: str,
    date: date | None = None,
    cycle: str = Query(default="00", pattern=r"^(00|06|12|18)$"),
    model: str = Query(default="ifs", pattern=r"^(ifs|aifs)$"),
    step: int | None = None,
    target: datetime | None = Query(default=None, alias="target"),
) -> dict[str, object]:
    """ECMWF forecast vertical profile for one station.

    Use *step* (hours after initialization) or *target* (ISO-8601
    valid time) to select a single profile.
    """
    try:
        point = resolve_forecast_location(location)
    except StationLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    cadence = 6 if model == "aifs" else 3
    if step is not None and (
        step < 0 or step > 144 or step % cadence != 0
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{model.upper()} sounding step must be between 0 and 144 "
                f"hours at a {cadence}-hour interval"
            ),
        )

    initialized_at = _build_initialized_at(date, cycle)
    requested_step = step
    if target is not None:
        target_utc = (
            target.replace(tzinfo=timezone.utc)
            if target.tzinfo is None
            else target.astimezone(timezone.utc)
        )
        requested_step = int(
            round((target_utc - initialized_at).total_seconds() / 3600)
        )
    if requested_step is None:
        raise HTTPException(
            status_code=422,
            detail="Specify one forecast step or target valid time",
        )
    if (
        requested_step < 0
        or requested_step > 144
        or requested_step % cadence != 0
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{model.upper()} sounding step must be between 0 and 144 "
                f"hours at a {cadence}-hour interval"
            ),
        )

    try:
        _, pres_path = await asyncio.to_thread(
            retrieve_ecmwf_forecast,
            initialized_at=initialized_at,
            cache_root=FORECAST_CACHE_ROOT,
            model=model,
            include_surface=False,
            latitude=point["latitude"],
            longitude=point["longitude"],
            backend="open-data",
            allow_download=False,
            cached_step=requested_step,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"ECMWF {model.upper()} forecast unavailable: {exc}",
        )

    soundings = await asyncio.to_thread(
        extract_sounding_forecast,
        pres_path,
        station_id=point["id"],
        station_name=point["name"],
        latitude=point["latitude"],
        longitude=point["longitude"],
        initialized_at=initialized_at,
        step_hours=requested_step,
    )
    if not soundings:
        raise HTTPException(status_code=422, detail="Could not decode forecast sounding")

    if target is not None:
        matches = [s for s in soundings if s.step_hours == requested_step]
        if not matches:
            raise HTTPException(status_code=404, detail=f"No forecast at {target}")
        return matches[0].model_dump(mode="json")

    if requested_step is not None:
        matches = [s for s in soundings if s.step_hours == requested_step]
        if not matches:
            raise HTTPException(
                status_code=404,
                detail=f"No forecast at step +{requested_step}h",
            )
        return matches[0].model_dump(mode="json")
    raise HTTPException(status_code=404, detail="Forecast sounding not found")


@app.get("/api/v1/forecast/sounding/{location}/interactive")
async def interactive_sounding_forecast(
    location: str,
    date: date | None = None,
    cycle: str = Query(default="00", pattern=r"^(00|06|12|18)$"),
    model: str = Query(default="ifs", pattern=r"^(ifs|aifs)$"),
    step: int = Query(default=24, ge=0, le=144),
) -> dict[str, object]:
    """Return a forecast profile in the observed interactive-chart schema."""
    payload = await sounding_forecast(
        location=location,
        date=date,
        cycle=cycle,
        model=model,
        step=step,
        target=None,
    )
    valid_at = datetime.fromisoformat(str(payload["valid_at"]))
    station_id = str(payload["station_id"])
    profile_station_id = station_id if station_id.isdigit() else "00000"
    latitude = float(payload["latitude"])
    longitude = float(payload["longitude"])
    levels = [
        SoundingLevel(
            observed_at=valid_at,
            longitude=longitude,
            latitude=latitude,
            pressure_hpa=float(level["pressure_hpa"]),
            geopotential_height_m=level.get("height_gpm"),
            temperature_c=level.get("temperature_c"),
            dewpoint_c=level.get("dewpoint_c"),
            relative_humidity_pct=level.get("relative_humidity_pct"),
            wind_direction_deg=level.get("wind_direction_deg"),
            wind_speed_ms=level.get("wind_speed_ms"),
        )
        for level in payload["levels"]
    ]
    profile = SoundingProfile(
        station_id=profile_station_id,
        valid_at=valid_at,
        source=str(payload["source"]),
        source_url="https://www.ecmwf.int/en/forecasts/datasets/open-data",
        fetched_at=datetime.now(timezone.utc),
        cache_status="forecast",
        level_count=len(levels),
        surface_pressure_hpa=max(
            level.pressure_hpa for level in levels
        ),
        top_pressure_hpa=min(level.pressure_hpa for level in levels),
        station_longitude=longitude,
        station_latitude=latitude,
        levels=levels,
    )
    diagnostics = await asyncio.to_thread(
        calculate_sounding_diagnostics,
        profile,
    )
    return {
        "profile": profile.model_dump(mode="json"),
        "diagnostics": diagnostics.model_dump(mode="json"),
        "station_name": payload["station_name"],
        "requested_location": station_id,
        "model": model,
        "step_hours": step,
    }


def _build_initialized_at(
    init_date: date | None,
    cycle: str,
) -> datetime:
    return datetime(
        (init_date or date.today()).year,
        (init_date or date.today()).month,
        (init_date or date.today()).day,
        int(cycle),
        tzinfo=timezone.utc,
    )


def resolve_forecast_location(query: str) -> dict[str, object]:
    """Resolve a national station query or a ``latitude,longitude`` pair."""
    normalized = query.strip()
    coordinate_match = re.fullmatch(
        r"\s*([+-]?\d+(?:\.\d+)?)\s*[,，]\s*"
        r"([+-]?\d+(?:\.\d+)?)\s*",
        normalized,
    )
    if coordinate_match is not None:
        latitude = float(coordinate_match.group(1))
        longitude = float(coordinate_match.group(2))
        if not -90 <= latitude <= 90:
            raise StationLookupError("纬度必须在 -90 到 90 之间")
        if not -180 <= longitude <= 180:
            raise StationLookupError("经度必须在 -180 到 180 之间")
        identifier = f"{latitude:.4f},{longitude:.4f}"
        return {
            "id": identifier,
            "name": f"{latitude:.2f}°, {longitude:.2f}°",
            "latitude": latitude,
            "longitude": longitude,
        }

    record = resolve_station(normalized)
    return {
        "id": record.wmo_id,
        "name": record.display_name,
        "latitude": record.latitude,
        "longitude": record.longitude,
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/brand", StaticFiles(directory=BRAND_DIR), name="brand")
app.mount("/products", StaticFiles(directory=PRODUCT_DATA_DIR), name="products")
app.mount("/previews", StaticFiles(directory=PREVIEW_DATA_DIR), name="previews")
