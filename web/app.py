import asyncio
import io
import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from time import monotonic
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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
    OgimetError,
    QWeatherError,
    RealtimeObservation,
    STATION_REGIONS,
    StationLookupError,
    SurfaceObservationSeries,
    WorldStation,
    close_qweather_client,
    fetch_ogimet_series,
    fetch_qweather_hourly,
    fetch_qweather_realtime_with_fallback,
    fetch_qweather_series,
    place_records,
    render_legacy_observation_png,
    resolve_place,
    resolve_station,
    resolve_world_station,
    search_places,
    search_stations,
    search_world_stations,
    station_records,
    stations_in_region,
    world_station_records,
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
from meteostation.sounding.wis2_profile import Wis2SoundingArchive, Wis2SoundingNotFound
from meteostation.weather_map import (
    NrlCycloneUnavailable,
    WeatherMapCatalog,
    WeatherMapConfig,
    WeatherMapDomain,
    WeatherMapPlan,
    build_weather_map_plan,
    fetch_nrl_tropical_cyclones,
    read_preview_catalog,
)
from meteostation.forecast import (
    extract_sounding_forecast,
    extract_surface_forecast,
    retrieve_ecmwf_forecast,
)
from meteostation.forecast.collector import load_forecast_collector_config
from meteostation.forecast.manifest import (
    CycleLease,
    ForecastManifest,
    LeaseUnavailable,
    validate_cycle_files,
)
from meteostation.ensemble import ensemble_capability_report, load_snapshot, summarize_members, threshold_support, cluster_scenarios
from meteostation.ensemble_sources import fetch_point_ensemble
from meteostation.cyclone_products import cluster_tracks, cyclone_capability_report, load_wnc_snapshot
from meteostation.historical_similarity import similarity_score
from meteostation.ibtracs import analogs as ibtracs_analogs, search_storms as search_ibtracs_storms
from meteostation.health import (
    HealthMetrics,
    PAGE_PATHS,
    collect_data_health,
    looks_like_bot,
    qweather_registry,
)
from meteostation.reanalysis import (
    FIELDS as REANALYSIS_FIELDS,
    ReanalysisUnavailable,
    retrieve_reanalysis_grid,
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
FORECAST_MANIFEST_PATH = (
    PROJECT_ROOT / "data" / "state" / "manifest" / "current.json"
)
FORECAST_COLLECTOR_CONFIG_PATH = (
    PROJECT_ROOT / "config" / "forecast_collector.json"
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
HEALTH_STATE_PATH = PROJECT_ROOT / "data" / "state" / "health.json"
GLOBAL_SOUNDING_STATE_PATH = (
    PROJECT_ROOT / "data" / "state" / "global_sounding_collector.json"
)
GLOBAL_SOUNDING_STATIONS_PATH = (
    PROJECT_ROOT / "data" / "state" / "global_sounding_stations.json"
)
WIS2_SOUNDING_STATE_PATH = (
    PROJECT_ROOT / "data" / "state" / "wis2_sounding_collector.json"
)

wyoming_client = WyomingSoundingClient(cache_root=RAW_DATA_DIR)
wis2_archive = Wis2SoundingArchive(RAW_DATA_DIR / "wis2_soundings")
weather_map_catalog = WeatherMapCatalog(
    config_path=WEATHER_MAP_CONFIG_PATH,
    catalog_path=WEATHER_MAP_CATALOG_PATH,
)
observation_plot_lock = asyncio.Lock()
observation_series_cache: dict[
    tuple[str, str, str, str], tuple[float, SurfaceObservationSeries]
] = {}
observation_series_locks: dict[tuple[str, str, str, str], asyncio.Lock] = {}
observation_refresh_tasks: dict[
    tuple[str, str, str, str], asyncio.Task
] = {}
guestbook_lock = asyncio.Lock()
weather_map_station_cache: dict[
    tuple[date, str], tuple[float, tuple[dict[str, object], ...]]
] = {}
reanalysis_jobs: dict[str, dict[str, object]] = {}
reanalysis_job_lock = asyncio.Lock()
reanalysis_worker_slots = asyncio.Semaphore(2)
traffic = RuntimeTraffic(TRAFFIC_STATE_PATH)
health_metrics = HealthMetrics(HEALTH_STATE_PATH)
qweather_registry.register(health_metrics.record_qweather)
admin_security = HTTPBasic(auto_error=False)
PRODUCT_DATA_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_DATA_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def application_lifespan(_app: FastAPI):
    warm_task = asyncio.create_task(_warm_primary_observation())
    yield
    if not warm_task.done():
        warm_task.cancel()
    await close_qweather_client()


async def _warm_primary_observation() -> None:
    """Warm the shared upstream connection and the primary-station series."""
    try:
        series = await fetch_qweather_series(
            resolve_station("58362"),
            mode="past24h",
        )
    except (QWeatherError, StationLookupError):
        return
    observation_series_cache[("58362", "past24h", "today", "current")] = (
        monotonic() + 3600,
        series,
    )


app = FastAPI(
    title="云海观象台 API",
    description="CloudyLake's Observatory 网站与气象数据服务。Powered with Codex & Deepseek.",
    version="2.3.0",
    lifespan=application_lifespan,
)


@app.middleware("http")
async def count_application_traffic(request: Request, call_next):
    started = monotonic()
    response = await call_next(request)
    latency_ms = (monotonic() - started) * 1000
    path = request.url.path
    try:
        response_bytes = int(response.headers.get("content-length", "0"))
    except ValueError:
        response_bytes = 0
    traffic.record(path, response.status_code, response_bytes)
    if path.startswith("/api/"):
        health_metrics.record_api_latency(latency_ms)
    is_page = path in PAGE_PATHS
    user_agent = request.headers.get("user-agent")
    is_bot = not user_agent or looks_like_bot(user_agent)
    if is_page and not is_bot:
        health_metrics.record_page_latency(latency_ms)
        if 200 <= response.status_code < 400:
            # Only successful responses on real page routes count as page
            # views, deduplicated per anonymous session and day.
            session_id = request.cookies.get("cl_session")
            if not session_id or not re.fullmatch(r"[0-9a-f]{16,32}", session_id):
                session_id = secrets.token_hex(8)
                response.set_cookie(
                    "cl_session",
                    session_id,
                    max_age=86400,
                    httponly=True,
                    samesite="lax",
                    secure=True,
                )
            traffic.record_page_view(session_id, path)
    return response


@app.get("/", include_in_schema=False)
async def homepage() -> FileResponse:
    return FileResponse(STATIC_DIR / "about.html")


@app.get("/analysis", include_in_schema=False)
async def analysis_page() -> FileResponse:
    """Legacy China analysis workbench, now with an explicit route."""
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


@app.get("/reanalysis", include_in_schema=False)
async def reanalysis_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "reanalysis.html")


@app.get("/about", include_in_schema=False)
async def about_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "about.html")


@app.get("/colorbar-translator", include_in_schema=False)
async def colorbar_translator_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "colorbar-translator.html")


@app.get("/ensemble", include_in_schema=False)
async def ensemble_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "ensemble.html")


@app.get("/cyclones", include_in_schema=False)
async def cyclones_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "cyclones.html")


@app.get("/history/similar", include_in_schema=False)
async def similar_history_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "history-similar.html")


@app.get("/api/v1/ensemble/status")
async def ensemble_status() -> dict[str, object]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "products": ensemble_capability_report(PROJECT_ROOT),
        "policy": "Point products use real native ensemble members with a bounded memory cache; global raw fields are not retained.",
    }


@app.get("/api/v1/ensemble/point")
async def ensemble_point(
    model: Literal["aifs-ens", "wn2"] = Query("aifs-ens"),
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> dict[str, object]:
    try:
        return await fetch_point_ensemble(model, lat, lon)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"集合资料暂不可用：{exc}") from exc


@app.get("/api/v1/ensemble/snapshot/{model}")
async def ensemble_snapshot(model: str) -> dict[str, object]:
    normalized = model.casefold()
    path = PRODUCT_DATA_DIR / "ensembles" / normalized / "latest.json"
    if not path.exists():
        raise HTTPException(status_code=503, detail={"status": "not_configured", "model": normalized, "message": "Validated AIFS ENS/WeatherNext 2 derived data is not configured on this host."})
    try:
        snapshot = load_snapshot(path)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail=f"Invalid ensemble snapshot: {exc}") from exc
    return {
        "model": snapshot.model,
        "initialized_at": snapshot.initialized_at.isoformat(),
        "steps": list(snapshot.steps),
        "members": snapshot.members,
        "variables": list(snapshot.variables),
        "data": snapshot.payload.get("data", {}),
    }


@app.get("/api/v1/cyclones/status")
async def cyclones_status() -> dict[str, object]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "wnc": cyclone_capability_report(PROJECT_ROOT),
        "official_sources": [
            {"label": "WeatherNext Cyclones / Weather Lab", "url": "https://www.weatherlab.ai/"},
            {"label": "Google DeepMind WeatherNext", "url": "https://deepmind.google/science/weathernext/"},
        ],
        "policy": "WNC 1000-member tracks are never substituted with WN2, AIFS or official warning tracks.",
    }


@app.get("/api/v1/cyclones/wnc/latest")
async def wnc_latest() -> dict[str, object]:
    path = PRODUCT_DATA_DIR / "cyclones" / "wnc-latest.json"
    if not path.exists():
        raise HTTPException(status_code=503, detail="尚未取得可公开展示的 WeatherNext Cyclones 派生轨迹")
    try:
        return await asyncio.to_thread(load_wnc_snapshot, path)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail=f"WNC 派生产品校验失败：{exc}") from exc


@app.get("/api/v1/cyclones/current")
async def current_cyclones() -> dict[str, object]:
    """Return an explicitly labelled global official-warning registry."""
    valid_at = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    archive_directory = RAW_DATA_DIR / "cyclones" / f"{valid_at:%Y}" / f"{valid_at:%m}" / f"{valid_at:%d}" / f"{valid_at:%H}"
    domain = WeatherMapDomain(west=-180, east=180, south=-60, north=70, resolution_degrees=1, projection="plate-carree")
    markers = []
    nrl_error = None
    try:
        markers = await asyncio.to_thread(
            fetch_nrl_tropical_cyclones,
            valid_at=valid_at,
            domain=domain,
            archive_directory=archive_directory,
            timeout_seconds=12,
        )
    except NrlCycloneUnavailable as exc:
        nrl_error = str(exc)
    if not markers:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.get("https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH", params={"eventlist": "TC"})
                response.raise_for_status()
                features = response.json().get("features", [])
            systems = []
            for feature in features:
                props = feature.get("properties", {})
                geometry = feature.get("geometry", {})
                coordinates = geometry.get("coordinates", [])
                if str(props.get("iscurrent", "")).casefold() != "true" or len(coordinates) < 2:
                    continue
                severity = props.get("severitydata", {}) or {}
                systems.append({
                    "id": f"GDACS-{props.get('eventid')}", "kind": "tropical", "valid_at": props.get("datemodified") or valid_at.isoformat(),
                    "latitude": coordinates[1], "longitude": coordinates[0], "name": props.get("eventname"),
                    "central_pressure_hpa": None, "maximum_wind_ms": round(float(severity.get("severity", 0)) / 3.6, 1) if severity.get("severityunit") == "km/h" else None,
                    "source": props.get("url", {}).get("report", "https://www.gdacs.org/"), "confidence": "medium", "alert_level": props.get("alertlevel"),
                })
            return {
                "status": "available",
                "valid_at": valid_at.isoformat(),
                "systems": systems,
                "source_role": "GDACS-global-situational-reference",
                "disclaimer": "GDACS 是全球灾害态势参考层，不是 WNC 集合成员。",
            }
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            return {"status": "source_unavailable", "systems": [], "detail": nrl_error or str(exc), "valid_at": valid_at.isoformat()}
    return {
        "status": "available",
        "valid_at": valid_at.isoformat(),
        "systems": [marker.model_dump(mode="json") for marker in markers],
        "source_role": "official-warning-reference",
        "disclaimer": "这些系统是官方警报参考层，不是 WNC 集合成员。",
    }


@app.get("/api/v1/history/similarity")
async def history_similarity(
    path_distance_km: float = Query(9999, ge=0),
    max_wind_kt: float = Query(0, ge=0),
    month: int = Query(1, ge=1, le=12),
    environment_distance: float = Query(9999, ge=0),
) -> dict[str, object]:
    current = {"path_distance_km": path_distance_km, "max_wind_kt": max_wind_kt, "month": month, "environment_distance": environment_distance}
    # The endpoint exposes the scoring contract; it intentionally does not
    # invent historical cases when no authoritative index is installed.
    return {"status": "index_not_configured", "scoring": similarity_score(current, current), "cases": []}


@app.get("/api/v1/history/storms")
async def history_storms(q: str = Query(default="", max_length=80), limit: int = Query(default=30, ge=1, le=100)) -> dict[str, object]:
    path = PRODUCT_DATA_DIR / "cyclones" / "ibtracs-wp.json.gz"
    storms = await asyncio.to_thread(search_ibtracs_storms, path, q, limit)
    return {"status": "available" if path.exists() else "index_not_configured", "storms": storms, "source": "NOAA IBTrACS v04r01"}


@app.get("/api/v1/history/analogs/{sid}")
async def history_analogs(sid: str, limit: int = Query(default=10, ge=1, le=30)) -> dict[str, object]:
    path = PRODUCT_DATA_DIR / "cyclones" / "ibtracs-wp.json.gz"
    if not path.exists():
        raise HTTPException(status_code=503, detail="IBTrACS 压缩索引尚未安装")
    result = await asyncio.to_thread(ibtracs_analogs, path, sid, limit)
    if result is None:
        raise HTTPException(status_code=404, detail="未找到该历史台风")
    return result


class ReanalysisRequest(BaseModel):
    valid_date: date
    hour: int = Field(ge=0, le=23)
    field: str = Field(min_length=1, max_length=40)
    pressure_hpa: int | None = Field(default=500, ge=1, le=1000)
    north: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)

    @field_validator("field")
    @classmethod
    def known_field(cls, value: str) -> str:
        if value not in REANALYSIS_FIELDS:
            raise ValueError("unknown ERA5 field")
        return value


@app.post("/api/v1/reanalysis/jobs", summary="提交临时 ERA5 区域查询")
async def create_reanalysis_job(query: ReanalysisRequest) -> dict[str, object]:
    if query.north <= query.south or query.east <= query.west:
        raise HTTPException(status_code=422, detail="区域边界顺序不正确")
    if query.north - query.south > 75 or query.east - query.west > 120:
        raise HTTPException(status_code=422, detail="单次查询范围过大，请缩小框选区域")
    valid_at = datetime(
        query.valid_date.year,
        query.valid_date.month,
        query.valid_date.day,
        query.hour,
        tzinfo=timezone.utc,
    )
    if valid_at > datetime.now(timezone.utc) - timedelta(days=5):
        raise HTTPException(
            status_code=422,
            detail="ERA5 通常延迟约 5 天，请选择更早的历史时次",
        )
    job_id = secrets.token_urlsafe(12)
    now = datetime.now(timezone.utc)
    async with reanalysis_job_lock:
        _expire_reanalysis_jobs(now)
        reanalysis_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "created_at": now.isoformat(),
            "query": query.model_dump(mode="json"),
        }
    asyncio.create_task(_run_reanalysis_job(job_id, query, valid_at))
    return reanalysis_jobs[job_id]


@app.get("/api/v1/reanalysis/jobs/{job_id}", summary="读取 ERA5 查询状态")
async def reanalysis_job(job_id: str) -> dict[str, object]:
    async with reanalysis_job_lock:
        _expire_reanalysis_jobs(datetime.now(timezone.utc))
        payload = reanalysis_jobs.get(job_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="查询任务不存在或已经过期")
        return dict(payload)


async def _run_reanalysis_job(
    job_id: str,
    query: ReanalysisRequest,
    valid_at: datetime,
) -> None:
    async with reanalysis_worker_slots:
        async with reanalysis_job_lock:
            reanalysis_jobs[job_id]["status"] = "retrieving"
            reanalysis_jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()
        try:
            result = await asyncio.to_thread(
                retrieve_reanalysis_grid,
                valid_at=valid_at,
                field_id=query.field,
                pressure_hpa=query.pressure_hpa,
                north=query.north,
                west=query.west,
                south=query.south,
                east=query.east,
            )
        except ReanalysisUnavailable as exc:
            health_metrics.record_task("reanalysis", False)
            async with reanalysis_job_lock:
                reanalysis_jobs[job_id].update(
                    status="failed",
                    detail=str(exc),
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
            return
        health_metrics.record_task("reanalysis", True)
        async with reanalysis_job_lock:
            reanalysis_jobs[job_id].update(
                status="complete",
                result=result,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )


def _expire_reanalysis_jobs(now: datetime) -> None:
    cutoff = now - timedelta(hours=1)
    for job_id, payload in list(reanalysis_jobs.items()):
        try:
            created_at = datetime.fromisoformat(str(payload["created_at"]))
        except (KeyError, ValueError):
            created_at = cutoff - timedelta(seconds=1)
        if created_at < cutoff:
            reanalysis_jobs.pop(job_id, None)


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


@app.get("/api/v1/health", include_in_schema=False)
async def health() -> dict[str, str]:
    # Backward-compatible alias of /health/live.
    return {"status": "alive", "service": "CloudyLake's Observatory"}


@app.get("/health/live", include_in_schema=False)
async def health_live() -> dict[str, str]:
    """Process liveness only — no dependency checks."""
    return {"status": "alive"}


def _weather_map_health_meta() -> dict[str, object]:
    """Newest weather-map cycle from products and previews catalogs."""
    product = weather_map_catalog.latest_product(layer_id="surface")
    previews = read_preview_catalog(WEATHER_MAP_PREVIEW_CATALOG_PATH)
    newest_preview = max(previews, key=lambda item: item.valid_at, default=None)
    latest_valid_at: str | None = None
    publication_status: str | None = None
    if product is not None:
        latest_valid_at = product.valid_at.isoformat()
        publication_status = "published"
    if newest_preview is not None and (
        latest_valid_at is None or newest_preview.valid_at.isoformat() > latest_valid_at
    ):
        latest_valid_at = newest_preview.valid_at.isoformat()
        publication_status = "development-preview"
    return {
        "latest_valid_at": latest_valid_at,
        "publication_status": publication_status,
    }


async def _health_data_report() -> dict[str, object]:
    return await asyncio.to_thread(
        collect_data_health,
        project_root=PROJECT_ROOT,
        metrics=health_metrics,
        max_stale_hours=_DEFAULT_MAX_STALE_HOURS,
        weather_map_meta=_weather_map_health_meta(),
        manifest_payload=forecast_manifest.load(),
        sounding_stations_payload=read_json(
            GLOBAL_SOUNDING_STATIONS_PATH, default={}
        ),
        global_sounding_payload=read_json(
            GLOBAL_SOUNDING_STATE_PATH, default={}
        ),
        wis2_payload=read_json(WIS2_SOUNDING_STATE_PATH, default={}),
        traffic_payload=traffic.snapshot(),
    )


@app.get("/health/ready", include_in_schema=False)
async def health_ready(response: Response) -> dict[str, object]:
    """Core dependencies and current products usable.

    Fails with 503 when the current forecast cycles or the latest weather
    map are missing or over age, so load balancers stop routing traffic
    while data is stale.
    """
    report = await _health_data_report()
    if report["status"] == "stale":
        detail: dict[str, object] = {
            "status": "not_ready",
            "forecast": report["forecast"],
            "weather_maps": report["weather_maps"],
        }
        return JSONResponse(status_code=503, content=detail)
    return {"status": "ready", "checked_at": report["checked_at"]}


@app.get("/health/data", include_in_schema=False)
async def health_data() -> dict[str, object]:
    """Per-source freshness report (always HTTP 200)."""
    return await _health_data_report()


@app.get("/metrics", include_in_schema=False)
async def metrics() -> dict[str, object]:
    """Internal monitoring values: counters, latency percentiles, disk."""
    report = await _health_data_report()
    traffic_snapshot = traffic.snapshot()
    return {
        "uptime_checked_at": report["checked_at"],
        "traffic": {
            "requests": traffic_snapshot.get("requests"),
            "response_bytes": traffic_snapshot.get("response_bytes"),
            "status_counts": traffic_snapshot.get("status_counts"),
            "path_counts": traffic_snapshot.get("path_counts"),
            "monthly_page_views": traffic_snapshot.get("monthly_page_views"),
        },
        "latency": report["http"],
        "qweather": report["qweather"],
        "tasks": report["tasks"],
        "disk": report["disk"],
        "forecast": report["forecast"],
        "weather_maps": report["weather_maps"],
        "wis2": report["wis2"],
    }


@app.get("/api/v1/status")
async def project_status() -> dict[str, object]:
    return {
        "version": "V2.4.0",
        "stage": "compact-observatory-and-operational-derived-products",
        "updated_at": "2026-08-31",
        "archive_policy": "soundings-saved-surface-query-no-store",
        "modules": [
            {
                "id": "china-map",
                "label": "中国天气主页",
                "status": "automatic-analysis-running",
            },
            {"id": "historical-reanalysis", "label": "历史再分析", "status": "query-on-demand"},
            {"id": "aifs-ens", "label": "AIFS ENS预报", "status": "real-point-ensemble-on-demand"},
            {"id": "wn2", "label": "WeatherNext 2全球集合", "status": "real-point-ensemble-on-demand"},
            {"id": "wnc", "label": "WeatherNext Cyclones千成员", "status": "adapter-ready-not-configured"},
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
                "label": "Wyoming 探空回退",
                "role": "fallback",
                "url": "https://weather.uwyo.edu/wsgi/sounding",
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
                "role": "primary",
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
    congestion = server_congestion_snapshot(PROJECT_ROOT)
    # The three status cells must reflect resources *and* data availability:
    # stale products can never show a green all-clear.
    data_health = await _health_data_report()
    data_status = str(data_health.get("status", "unknown"))
    base_level = int(congestion.get("level", 1))
    if data_status == "stale":
        congestion = {
            **congestion,
            "level": 1,
            "label": "资料过期",
            "data_status": "stale",
        }
    elif data_status == "ok" and base_level == 3:
        congestion = {
            **congestion,
            "data_status": "fresh",
        }
    else:
        congestion = {
            **congestion,
            "data_status": "degraded",
        }
    return {
        **traffic.snapshot(),
        "congestion": congestion,
        "data_health": {
            "status": data_status,
            "forecast": data_health.get("forecast"),
            "weather_maps": data_health.get("weather_maps"),
        },
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
    "/api/v1/weather-maps/latest",
    summary="读取最近完成的中国天气图产品",
)
async def latest_weather_map_product(
    layer: str = Query(default="composite", min_length=1, max_length=40),
) -> dict[str, object]:
    configuration = weather_map_catalog.configuration()
    known_layers = {item.id for item in configuration.layers}
    if layer not in known_layers:
        raise HTTPException(status_code=422, detail="unknown weather-map layer")

    preview_layer = "surface" if layer == "composite" else layer
    previews = [
        item
        for item in read_preview_catalog(WEATHER_MAP_PREVIEW_CATALOG_PATH)
        if item.layer_id == preview_layer
    ]
    preview = max(previews, key=lambda item: item.valid_at, default=None)
    product = weather_map_catalog.latest_product(layer_id=layer)
    if product is not None and (
        preview is None or product.valid_at >= preview.valid_at
    ):
        return {
            "layer": layer,
            "product": product.model_dump(mode="json"),
            "kind": "product",
        }
    return {
        "layer": layer,
        "product": preview.model_dump(mode="json") if preview else None,
        "kind": "preview" if preview else None,
    }


@app.get(
    "/api/v1/weather-maps/sounding-stations",
    summary="读取中国天气图探空站及本地归档状态",
)
async def weather_map_sounding_stations(
    sounding_date: date = Query(alias="date"),
    cycle: Literal["00", "12"] = Query(default="00"),
) -> dict[str, object]:
    profiles = await asyncio.to_thread(
        _weather_map_station_profiles,
        sounding_date,
        cycle,
    )
    configuration = weather_map_catalog.configuration()
    return {
        "date": sounding_date,
        "cycle": cycle,
        "station_count": len(configuration.sounding_stations),
        "updated_count": len(profiles),
        "profiles": profiles,
    }


def _weather_map_station_profiles(
    sounding_date: date,
    cycle: Literal["00", "12"],
) -> tuple[dict[str, object], ...]:
    """Build a compact payload with a short cache for minute-level updates."""
    cache_key = (sounding_date, cycle)
    cached = weather_map_station_cache.get(cache_key)
    now = monotonic()
    if cached is not None and cached[0] > now:
        return cached[1]
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
        ordered = sorted(
            profile.levels,
            key=lambda level: level.pressure_hpa,
            reverse=True,
        )
        selected: list[SoundingLevel] = []
        for target_pressure in (None, 850.0, 500.0, 200.0):
            candidate = (
                ordered[0]
                if target_pressure is None
                else min(
                    ordered,
                    key=lambda level: abs(level.pressure_hpa - target_pressure),
                )
            )
            if all(
                abs(candidate.pressure_hpa - item.pressure_hpa) > 0.01
                for item in selected
            ):
                selected.append(candidate)
        profiles.append(
            {
                "wmo_id": station.wmo_id,
                "profile": {
                    "valid_at": profile.valid_at.isoformat(),
                    "levels": [item.model_dump(mode="json") for item in selected],
                },
            }
        )
    result = tuple(profiles)
    weather_map_station_cache[cache_key] = (now + 30.0, result)
    return result


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


def resolve_observation_station(query: str) -> tuple[object, str]:
    """Resolve a query to ``(station, source)``.

    ``source`` is ``"qweather"`` for Chinese national stations or ``"ogimet"``
    for everything else: any 5-digit WMO id can be queried through OGIMET even
    when it is missing from the bundled world directory (which then supplies
    the name and coordinates when available).
    """
    try:
        return resolve_station(query), "qweather"
    except StationLookupError:
        pass
    world = resolve_world_station(query)
    if world is not None:
        return world, "ogimet"
    normalized = query.strip()
    if re.fullmatch(r"\d{5}", normalized):
        return (
            WorldStation(
                wmo_id=normalized,
                name=normalized,
                country_code="",
                latitude=0.0,
                longitude=0.0,
                elevation_m=0.0,
            ),
            "ogimet",
        )
    raise StationLookupError(
        f"找不到“{query}”：可输入中国站名或任意 5 位 WMO 站号（含国外站）"
    )


def _observation_station_payload(station: object, source: str) -> dict[str, object]:
    payload = station.as_dict()
    if source == "qweather":
        payload["source"] = "china"
        payload["country_code"] = "CN"
    return payload


def _sounding_station_matches(query: str) -> list[dict[str, object]]:
    """Search the configured China upper-air inventory, including Chinese names."""
    normalized = query.strip().casefold()
    if not normalized:
        return []
    exact: list[dict[str, object]] = []
    partial: list[dict[str, object]] = []
    for station in weather_map_catalog.configuration().sounding_stations:
        payload = {
            "wmo_id": station.wmo_id,
            "name": station.name,
            "display_name": station.name,
            "country_code": "CN",
            "latitude": station.latitude,
            "longitude": station.longitude,
            "elevation_m": None,
            "source": "sounding",
        }
        keys = (station.wmo_id.casefold(), station.name.casefold())
        if normalized in keys:
            exact.append(payload)
        elif any(normalized in key for key in keys):
            partial.append(payload)
    return [*exact, *partial]


@app.get(
    "/api/v1/stations/search",
    summary="按 WMO 站号或中文站名检索内置气象站表（含国外站）",
)
async def station_search(
    q: str = Query(min_length=1, max_length=40),
    limit: int = Query(default=8, ge=1, le=20),
) -> dict[str, object]:
    china = [
        _observation_station_payload(station, "qweather")
        for station in search_stations(q, limit=limit)
    ]
    sounding = _sounding_station_matches(q)
    world = [
        station.as_dict()
        for station in search_world_stations(q, limit=limit)
    ]
    combined: list[dict[str, object]] = []
    seen: set[str] = set()
    for station in [*china, *sounding, *world]:
        station_id = str(station["wmo_id"])
        if station_id in seen:
            continue
        seen.add(station_id)
        combined.append(station)
        if len(combined) >= limit:
            break
    return {
        "query": q,
        "stations": combined,
    }


@app.get(
    "/api/v1/places/search",
    summary="按名称检索全国行政区划地名（省/市/区县）",
)
async def place_search(
    q: str = Query(min_length=1, max_length=40),
    limit: int = Query(default=8, ge=1, le=20),
) -> dict[str, object]:
    return {
        "query": q,
        "places": search_places(q, limit=limit),
        "total": len(place_records()),
    }


@app.get(
    "/api/v1/stations/resolve",
    summary="将 WMO 站号或中文站名解析为唯一站点（含国外站）",
)
async def station_resolve(
    q: str = Query(min_length=1, max_length=40),
) -> dict[str, object]:
    sounding = _sounding_station_matches(q)
    normalized = q.strip().casefold()
    exact_sounding = [
        item
        for item in sounding
        if normalized in {
            str(item["wmo_id"]).casefold(),
            str(item["name"]).casefold(),
            str(item["display_name"]).casefold(),
        }
    ]
    if len(exact_sounding) == 1:
        return exact_sounding[0]
    try:
        station, source = resolve_observation_station(q)
        return _observation_station_payload(station, source)
    except StationLookupError as exc:
        if len(sounding) == 1:
            return sounding[0]
        if len(sounding) > 1:
            options = "、".join(
                f"{item['display_name']} {item['wmo_id']}"
                for item in sounding[:6]
            )
            raise HTTPException(
                status_code=422,
                detail=f"请输入更完整的高空站名或站号：{options}",
            ) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/api/v1/stations/region/{region}",
    summary="读取分区国家站与省级边界，供可点击站点地图使用",
)
async def station_region_map(region: str) -> dict[str, object]:
    try:
        return _station_region_payload(region)
    except StationLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/api/v1/stations/china",
    summary="读取全国国家站与省级边界，供可拖动站点地图使用",
)
async def station_china_map() -> dict[str, object]:
    return _station_china_payload()


@app.get(
    "/api/v1/stations/world",
    summary="读取全球高空气象站目录，供世界地图选站使用",
)
async def station_world_map() -> dict[str, object]:
    stations = world_station_records()
    return {
        "station_count": len(stations),
        "stations": [station.as_dict() for station in stations],
    }


async def _ogimet_realtime(
    station_id: str,
    station: WorldStation,
) -> RealtimeObservation:
    """Latest OGIMET SYNOP as the realtime observation for a world station."""
    series = await fetch_ogimet_series(
        station_id=station_id,
        mode="past24h",
        station_info=station.as_dict(),
    )
    latest = series.observations[-1] if series.observations else None
    if latest is None:
        raise OgimetError("OGIMET 没有返回该站实时观测")
    return RealtimeObservation(
        station_id=station_id,
        source=series.source,
        source_url=series.source_url,
        temperature_c=latest.temperature_c,
        relative_humidity_pct=latest.relative_humidity_pct,
        station_pressure_hpa=latest.station_pressure_hpa,
        wind_direction_deg=latest.wind_direction_deg,
        wind_speed_ms=latest.wind_speed_ms,
        precipitation_1h_mm=latest.precipitation_1h_mm,
        visibility_km=latest.visibility_km,
        observed_at=latest.observed_at,
    )


@app.get(
    "/api/v1/observations/realtime/{station_id}",
    response_model=RealtimeObservation,
    summary="查询气象站实时观测（含国外站）",
)
async def realtime_observation(station_id: str) -> RealtimeObservation:
    validate_station_id(station_id)
    try:
        station, source = resolve_observation_station(station_id)
    except StationLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if source == "qweather":
        try:
            return await fetch_qweather_realtime_with_fallback(station_id)
        except QWeatherError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        return await _ogimet_realtime(station_id, station)
    except OgimetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get(
    "/api/v1/observations/hourly/{station_id}",
    response_model=RealtimeObservation,
    summary="查询指定整点的地面观测（含国外站）",
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
        station, source = resolve_observation_station(station_id)
    except StationLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if source == "qweather":
        try:
            return await fetch_qweather_hourly(station_id, observed_at)
        except QWeatherError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        series = await fetch_ogimet_series(
            station_id=station_id,
            mode="history",
            historical_date=observed_at.date(),
            station_info=station.as_dict(),
        )
    except OgimetError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    match = next(
        (
            item
            for item in series.observations
            if item.observed_at.hour == observed_at.hour
            and item.observed_at.date() == observed_at.date()
        ),
        None,
    )
    if match is None:
        raise HTTPException(
            status_code=404,
            detail="OGIMET 在该整点没有观测记录",
        )
    return RealtimeObservation(
        station_id=station_id,
        source=series.source,
        source_url=series.source_url,
        temperature_c=match.temperature_c,
        relative_humidity_pct=match.relative_humidity_pct,
        station_pressure_hpa=match.station_pressure_hpa,
        wind_direction_deg=match.wind_direction_deg,
        wind_speed_ms=match.wind_speed_ms,
        precipitation_1h_mm=match.precipitation_1h_mm,
        visibility_km=match.visibility_km,
        observed_at=match.observed_at,
    )


async def _fetch_observation_series(
    station: WorldStation,
    source: str,
    mode: str,
    historical_date: date | None,
    history_window: str,
) -> SurfaceObservationSeries:
    """One normalized upstream read shared by API, cache and PNG export."""
    if source == "qweather":
        return await fetch_qweather_series(
            station,
            mode=mode,
            historical_date=historical_date,
            history_window=history_window,
        )
    return await fetch_ogimet_series(
        station_id=station.wmo_id,
        mode=mode,
        historical_date=historical_date,
        station_info=station.as_dict(),
    )


async def _refresh_observation_series(
    key: tuple[str, str, str, str],
    station: WorldStation,
    source: str,
    mode: str,
    historical_date: date | None,
    history_window: str,
) -> None:
    """Background stale-while-revalidate refresh for one series key."""
    try:
        series = await _fetch_observation_series(
            station,
            source,
            mode,
            historical_date,
            history_window,
        )
        ttl = 3600 if mode == "past24h" else 21600
        observation_series_cache[key] = (monotonic() + ttl, series)
        health_metrics.record_task("observation-refresh", True)
    except (QWeatherError, OgimetError):
        health_metrics.record_task("observation-refresh", False)
    finally:
        observation_refresh_tasks.pop(key, None)


@app.get(
    "/api/v1/observations/series/{station_id}",
    response_model=SurfaceObservationSeries,
    summary="查询24小时地面观测序列",
)
async def observation_series(
    station_id: str,
    mode: Literal["past24h", "history"] = Query(default="past24h"),
    historical_date: date | None = Query(default=None, alias="date"),
    history_window: Literal["00-00", "08-08", "20-20"] = Query(
        default="08-08",
        alias="window",
    ),
) -> SurfaceObservationSeries:
    validate_station_id(station_id)
    if mode == "history" and historical_date is None:
        raise HTTPException(status_code=422, detail="history mode requires date")
    if historical_date is not None and historical_date > datetime.now(timezone.utc).date():
        raise HTTPException(status_code=422, detail="date cannot be in the future")
    try:
        station, source = resolve_observation_station(station_id)
    except StationLookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    date_key = historical_date.isoformat() if historical_date else "today"
    window_key = history_window if mode == "history" else "current"
    key = (station_id, mode, date_key, window_key)
    now = monotonic()
    cached = observation_series_cache.get(key)
    if cached and cached[0] > now:
        return cached[1].model_copy(update={"cache_status": "memory-hit"})
    if cached:
        # Stale-while-revalidate: answer with the previous data at once and
        # refresh in the background (deduplicated per key).
        refresh_task = observation_refresh_tasks.get(key)
        if refresh_task is None or refresh_task.done():
            observation_refresh_tasks[key] = asyncio.create_task(
                _refresh_observation_series(
                    key,
                    station,
                    source,
                    mode,
                    historical_date,
                    history_window,
                )
            )
        return cached[1].model_copy(
            update={"cache_status": "stale-refreshing"}
        )
    key_lock = observation_series_locks.setdefault(key, asyncio.Lock())
    async with key_lock:
        cached = observation_series_cache.get(key)
        if cached and cached[0] > monotonic():
            return cached[1].model_copy(update={"cache_status": "memory-hit"})
        try:
            series = await _fetch_observation_series(
                station,
                source,
                mode,
                historical_date,
                history_window,
            )
        except (QWeatherError, OgimetError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        # The upstream table updates hourly. Reusing the normalized response
        # through the current hour avoids repeatedly waiting on a variable-
        # latency third-party page; real-time status remains a separate API.
        ttl = 3600 if mode == "past24h" else 21600
        observation_series_cache[key] = (monotonic() + ttl, series)
        if len(observation_series_cache) > 256:
            expired = [item for item, value in observation_series_cache.items() if value[0] <= monotonic()]
            for item in expired:
                observation_series_cache.pop(item, None)
                observation_series_locks.pop(item, None)
        return series


@app.get(
    "/api/v1/observations/plot",
    summary="生成24小时地面观测序列 PNG",
)
async def surface_observation_plot(
    station_query: str = Query(alias="station", min_length=1, max_length=40),
    mode: Literal["past24h", "history"] = Query(default="past24h"),
    historical_date: date | None = Query(default=None, alias="date"),
    history_window: Literal["08-08", "20-20"] = Query(
        default="08-08",
        alias="window",
    ),
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
    # PNG export reuses the normalized structured series (memory cache or a
    # single normalized fetch) instead of hitting the upstream page again.
    date_key = historical_date.isoformat() if historical_date else "today"
    window_key = history_window if mode == "history" else "current"
    key = (station.wmo_id, mode, date_key, window_key)
    cached = observation_series_cache.get(key)
    if cached is not None:
        series = cached[1]
    else:
        try:
            series = await fetch_qweather_series(
                station,
                mode=mode,
                historical_date=historical_date,
                history_window=history_window,
            )
        except QWeatherError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        ttl = 3600 if mode == "past24h" else 21600
        observation_series_cache[key] = (monotonic() + ttl, series)
    async with observation_plot_lock:
        try:
            result = await asyncio.to_thread(
                render_legacy_observation_png,
                station=station,
                mode=mode,
                historical_date=historical_date,
                history_window=history_window,
                series=series,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"静态实况图生成失败：{exc}",
            ) from exc
    filename = (
        f"{station.wmo_id}_{date_label.replace(' ', '-')}_{history_window if mode == 'history' else 'past24h'}_observations.png"
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
        return wis2_archive.load_profile(station_id, sounding_date, cycle)
    except (Wis2SoundingNotFound, OSError, ValueError, json.JSONDecodeError):
        pass
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
forecast_manifest = ForecastManifest(
    path=FORECAST_MANIFEST_PATH,
    cache_root=FORECAST_CACHE_ROOT,
)
_DEFAULT_MAX_STALE_HOURS = {"ifs": 18.0, "aifs": 30.0}
_forecast_max_stale_cache: dict[str, float] = {}


def _forecast_max_stale_hours(model: str) -> float:
    """Maximum allowed age for one model cycle, from collector config."""
    if not _forecast_max_stale_cache:
        try:
            config = load_forecast_collector_config(
                FORECAST_COLLECTOR_CONFIG_PATH
            )
            for name, hours in config.max_stale_hours.items():
                _forecast_max_stale_cache[name] = float(hours)
        except Exception:
            pass
    return _forecast_max_stale_cache.get(
        model,
        _DEFAULT_MAX_STALE_HOURS.get(model, 18.0),
    )


def _forecast_unavailable(
    model: str,
    *,
    reason: str,
    age_hours: float | None = None,
) -> HTTPException:
    """Structured 503 for missing or over-age forecast data (never 500)."""
    detail: dict[str, object] = {
        "status": "unavailable",
        "model": model,
        "reason": reason,
    }
    max_stale = _forecast_max_stale_hours(model)
    detail["max_stale_hours"] = max_stale
    if age_hours is not None:
        detail["age_hours"] = round(age_hours, 2)
    return HTTPException(status_code=503, detail=detail)


def _forecast_meta_payload(
    model: str,
    initialized_at: datetime,
    age_hours: float | None,
    degraded: bool,
) -> dict[str, object]:
    """Public degradation metadata attached to every forecast response."""
    return {
        "model": model,
        "initialized_at": initialized_at.isoformat(),
        "data_age_hours": round(
            age_hours
            if age_hours is not None
            else max(
                0.0,
                (
                    datetime.now(timezone.utc) - initialized_at
                ).total_seconds()
                / 3600.0,
            ),
            2,
        ),
        "degraded": degraded,
        "max_stale_hours": _forecast_max_stale_hours(model),
    }


def _resolve_forecast_cycle(
    model: str,
    field_type: Literal["surface", "pressure"],
    *,
    requested_at: datetime | None = None,
    reference: datetime | None = None,
) -> tuple[datetime, Path, bool, float]:
    """Resolve the freshest usable cycle via manifest + filesystem.

    The manifest is never trusted alone: both stores of the entry must exist
    with the recorded sizes.  ``previous`` is used only when ``current`` is
    missing or over age, and every non-current answer is flagged degraded.
    Returns ``(initialized_at, store_path, degraded, age_hours)``.

    Raises an ``HTTPException(503)`` with a structured payload when no cycle
    is within the configured maximum staleness.
    """
    now = reference or datetime.now(timezone.utc)
    max_stale = _forecast_max_stale_hours(model)
    slots = forecast_manifest.cycles().get(model, {})
    for slot in ("current", "previous"):
        entry = slots.get(slot)
        if entry is None:
            continue
        path = entry.path_for(field_type)
        expected_bytes = (
            entry.surface_bytes
            if field_type == "surface"
            else entry.pressure_bytes
        )
        if not path.exists() or path.stat().st_size != expected_bytes:
            # State/file divergence: ignore the manifest entry and look
            # further.  A vanished current is reported as degraded data
            # only if the previous cycle still passes validation.
            continue
        age_hours = entry.age_hours(now)
        if age_hours > max_stale:
            raise _forecast_unavailable(
                model,
                reason="stale",
                age_hours=age_hours,
            )
        return (
            entry.initialized_at,
            path,
            slot != "current",
            age_hours,
        )

    # Manifest missing or unusable: cross-validate directly from disk.
    fallback = _latest_cached_forecast_cycle(
        model=model,
        requested_at=requested_at,
        field_type=field_type,
    )
    if fallback is not None:
        age_hours = max(
            0.0,
            (now - fallback).total_seconds() / 3600.0,
        )
        if age_hours <= max_stale:
            path = (
                FORECAST_CACHE_ROOT
                / "ecmwf_forecast"
                / model
                / f"{fallback:%Y}"
                / f"{fallback:%m}"
                / f"{fallback:%d}"
            )
            matches = sorted(
                path.glob(
                    f"{model}_{fallback:%Y%m%d}_{fallback:%H}z_"
                    f"forecast_{field_type}_144h_*hourly.fast.nc"
                )
            )
            if matches:
                return fallback, matches[0], True, age_hours
    raise _forecast_unavailable(
        model,
        reason="missing",
    )


def _latest_cached_forecast_cycle(
    *,
    model: str,
    requested_at: datetime | None,
    field_type: Literal["surface", "pressure"],
) -> datetime | None:
    """Find the newest complete local field, optionally bounded by a cycle."""
    model_root = FORECAST_CACHE_ROOT / "ecmwf_forecast" / model
    pattern = re.compile(
        rf"^{re.escape(model)}_(\d{{8}})_(\d{{2}})z_"
        rf"forecast_{field_type}_144h_\d+hourly\.fast\.nc$"
    )
    candidates: list[datetime] = []
    if not model_root.is_dir():
        return None
    for path in model_root.rglob(
        f"{model}_*_forecast_{field_type}_144h_*hourly.fast.nc"
    ):
        match = pattern.match(path.name)
        if match is None:
            continue
        initialized_at = datetime.strptime(
            match.group(1) + match.group(2),
            "%Y%m%d%H",
        ).replace(tzinfo=timezone.utc)
        if requested_at is None or initialized_at <= requested_at:
            candidates.append(initialized_at)
    return max(candidates, default=None)


@app.get("/api/v1/forecast/cache/status")
async def forecast_cache_status() -> dict[str, object]:
    """Return the forecast-cycle monitor state without starting downloads.

    Every item is cross-validated against the filesystem, and the manifest
    slots are reported with their current age and usability, so this state
    is never a stale collector-only declaration.
    """
    state = read_json(
        FORECAST_COLLECTOR_STATE_PATH,
        default={
            "updated_at": None,
            "items": {},
            "last_run": None,
        },
    )
    now = datetime.now(timezone.utc)
    validated: dict[str, object] = {}
    items = state.get("items", {})
    if isinstance(items, dict):
        # Validate only complete items from the last seven days; older
        # declarations are pruned declarations and only slow the endpoint.
        recent_keys: list[tuple[datetime, str]] = []
        for key, item in items.items():
            if not isinstance(item, dict) or item.get("status") != "complete":
                continue
            parts = str(key).split("|")
            if len(parts) != 2:
                continue
            try:
                initialized_at = datetime.fromisoformat(parts[1])
            except ValueError:
                continue
            if now - initialized_at <= timedelta(days=7):
                recent_keys.append((initialized_at, str(key)))
        recent_keys.sort(reverse=True)
        recent_keys = recent_keys[:24]
        for _, key in recent_keys:
            item = items[key]
            parts = str(key).split("|")
            initialized_at = datetime.fromisoformat(parts[1])
            check = await asyncio.to_thread(
                validate_cycle_files,
                FORECAST_CACHE_ROOT,
                parts[0],
                initialized_at,
                require_fast=True,
            )
            item = {**item, "filesystem": check["ok"]}
            if not check["ok"]:
                item["validation_errors"] = check["errors"]
            validated[key] = item
    manifest_report: dict[str, object] = {}
    for model in FORECAST_MODELS:
        entry = forecast_manifest.cycles().get(model, {}).get("current")
        if entry is None:
            manifest_report[model] = {"available": False}
            continue
        files_present = (
            entry.path_for("surface").exists()
            and entry.path_for("pressure").exists()
            and entry.path_for("surface").stat().st_size
            == entry.surface_bytes
            and entry.path_for("pressure").stat().st_size
            == entry.pressure_bytes
        )
        manifest_report[model] = {
            "available": files_present,
            "initialized_at": entry.initialized_at.isoformat(),
            "age_hours": round(entry.age_hours(now), 2),
            "max_stale_hours": _forecast_max_stale_hours(model),
            "stale": entry.age_hours(now) > _forecast_max_stale_hours(model),
        }
    return {
        **state,
        "cross_validated_items": validated,
        "manifest": manifest_report,
    }


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
    actual_initialized_at = initialized_at
    age_hours: float | None = None
    degraded = False

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
    except FileNotFoundError:
        # This is a latest operational product, not a forecast archive.  Old
        # bookmarked URLs can outlive the rotating cache, so fall forward to
        # the freshest cycle that passes the manifest + filesystem check.
        actual_initialized_at, surf_path, degraded, age_hours = (
            await asyncio.to_thread(
                _resolve_forecast_cycle,
                model,
                "surface",
                requested_at=initialized_at,
            )
        )
    except Exception as exc:
        raise _forecast_unavailable(model, reason=f"read failed: {exc}") from exc

    try:
        lease = CycleLease(
            FORECAST_CACHE_ROOT,
            model,
            actual_initialized_at,
            exclusive=False,
        )
        try:
            lease.__enter__()
        except LeaseUnavailable:
            # Advisory lease unavailable (e.g. permissions): read anyway;
            # the manifest + size cross-check still guards the file set.
            lease = None
        try:
            forecast = await asyncio.to_thread(
                extract_surface_forecast,
                surf_path,
                station_id=point["id"],
                station_name=point["name"],
                latitude=point["latitude"],
                longitude=point["longitude"],
                initialized_at=actual_initialized_at,
            )
        finally:
            if lease is not None:
                lease.__exit__(None, None, None)
    except FileNotFoundError as exc:
        # The file vanished despite the lease being free (external removal);
        # surface the condition as a structured 503 instead of a 500.
        raise _forecast_unavailable(
            model,
            reason="file missing during read",
        ) from exc
    except Exception as exc:
        raise _forecast_unavailable(model, reason=str(exc)) from exc

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
    payload = forecast.model_dump(mode="json")
    payload["meta"] = {
        **_forecast_meta_payload(
            model,
            actual_initialized_at,
            age_hours,
            degraded,
        ),
        "forecast_horizon_hours": horizon,
    }
    return payload


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
    actual_initialized_at = initialized_at
    degraded = False
    age_hours: float | None = None
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
    except FileNotFoundError:
        actual_initialized_at, pres_path, degraded, age_hours = (
            await asyncio.to_thread(
                _resolve_forecast_cycle,
                model,
                "pressure",
                requested_at=initialized_at,
            )
        )
    except Exception as exc:
        raise _forecast_unavailable(model, reason=f"read failed: {exc}") from exc

    try:
        lease = CycleLease(
            FORECAST_CACHE_ROOT,
            model,
            actual_initialized_at,
            exclusive=False,
        )
        try:
            lease.__enter__()
        except LeaseUnavailable:
            lease = None
        try:
            soundings = await asyncio.to_thread(
                extract_sounding_forecast,
                pres_path,
                station_id=point["id"],
                station_name=point["name"],
                latitude=point["latitude"],
                longitude=point["longitude"],
                initialized_at=actual_initialized_at,
                step_hours=requested_step,
            )
        finally:
            if lease is not None:
                lease.__exit__(None, None, None)
    except FileNotFoundError as exc:
        raise _forecast_unavailable(
            model,
            reason="file missing during read",
        ) from exc
    except Exception as exc:
        raise _forecast_unavailable(model, reason=str(exc)) from exc
    if not soundings:
        raise HTTPException(status_code=422, detail="Could not decode forecast sounding")

    if target is not None:
        matches = [s for s in soundings if s.step_hours == requested_step]
        if not matches:
            raise HTTPException(status_code=404, detail=f"No forecast at {target}")
        result = matches[0].model_dump(mode="json")
        result["meta"] = _forecast_meta_payload(
            model,
            actual_initialized_at,
            age_hours,
            degraded,
        )
        return result

    if requested_step is not None:
        matches = [s for s in soundings if s.step_hours == requested_step]
        if not matches:
            raise HTTPException(
                status_code=404,
                detail=f"No forecast at step +{requested_step}h",
            )
        result = matches[0].model_dump(mode="json")
        result["meta"] = _forecast_meta_payload(
            model,
            actual_initialized_at,
            age_hours,
            degraded,
        )
        return result
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
        "meta": payload.get("meta"),
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


@lru_cache(maxsize=8)
def _station_region_payload(region: str) -> dict[str, object]:
    provinces = STATION_REGIONS.get(region)
    if provinces is None:
        raise StationLookupError(f"未知地区：{region}")
    stations = stations_in_region(region)
    geojson_path = PROJECT_ROOT / "中国_省.geojson"
    features: list[dict[str, object]] = []
    if geojson_path.exists():
        payload = json.loads(geojson_path.read_text(encoding="utf-8"))
        wanted_names = {_province_geojson_name(name) for name in provinces}
        features = [
            feature
            for feature in payload.get("features", [])
            if feature.get("properties", {}).get("name") in wanted_names
        ]
    coordinates: list[tuple[float, float]] = [
        (station.longitude, station.latitude) for station in stations
    ]
    for feature in features:
        _collect_geojson_coordinates(
            feature.get("geometry", {}).get("coordinates", []),
            coordinates,
        )
    longitudes = [item[0] for item in coordinates] or [73.0, 135.0]
    latitudes = [item[1] for item in coordinates] or [18.0, 54.0]
    return {
        "region": region,
        "regions": list(STATION_REGIONS),
        "provinces": list(provinces),
        "bounds": {
            "west": min(longitudes) - 0.35,
            "east": max(longitudes) + 0.35,
            "south": min(latitudes) - 0.25,
            "north": max(latitudes) + 0.25,
        },
        "boundaries": {"type": "FeatureCollection", "features": features},
        "stations": [station.as_dict() for station in stations],
    }


@lru_cache(maxsize=1)
def _station_china_payload() -> dict[str, object]:
    stations = list(station_records())
    geojson_path = PROJECT_ROOT / "中国_省.geojson"
    features: list[dict[str, object]] = []
    if geojson_path.exists():
        payload = json.loads(geojson_path.read_text(encoding="utf-8"))
        features = list(payload.get("features", []))
    city_geojson_path = PROJECT_ROOT / "中国_市.geojson"
    city_features: list[dict[str, object]] = []
    if city_geojson_path.exists():
        payload = json.loads(city_geojson_path.read_text(encoding="utf-8"))
        city_features = list(payload.get("features", []))
    return {
        "bounds": {
            "west": 73.0,
            "east": 135.0,
            "south": 18.0,
            "north": 54.0,
        },
        "boundaries": {"type": "FeatureCollection", "features": features},
        "city_boundaries": {"type": "FeatureCollection", "features": city_features},
        "stations": [station.as_dict() for station in stations],
    }


# Administrative boundary level-of-detail for the station picker map. The
# province layer ships with the repo; city and district layers come from the
# DataV GeoAtlas public dataset and are cached under data/geo/ (git-ignored).
PROVINCE_ADCODE_NAMES = {
    "110000": "北京市", "120000": "天津市", "130000": "河北省",
    "140000": "山西省", "150000": "内蒙古自治区", "210000": "辽宁省",
    "220000": "吉林省", "230000": "黑龙江省", "310000": "上海市",
    "320000": "江苏省", "330000": "浙江省", "340000": "安徽省",
    "350000": "福建省", "360000": "江西省", "370000": "山东省",
    "410000": "河南省", "420000": "湖北省", "430000": "湖南省",
    "440000": "广东省", "450000": "广西壮族自治区", "460000": "海南省",
    "500000": "重庆市", "510000": "四川省", "520000": "贵州省",
    "530000": "云南省", "540000": "西藏自治区", "610000": "陕西省",
    "620000": "甘肃省", "630000": "青海省", "640000": "宁夏回族自治区",
    "650000": "新疆维吾尔自治区", "710000": "台湾省", "810000": "香港特别行政区",
    "820000": "澳门特别行政区",
}
_DISTRICT_CACHE_ROOT = PROJECT_ROOT / "data" / "geo"


def _download_geojson(url: str) -> dict[str, object]:
    import urllib.request

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MeteoStation/2.3.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _point_in_ring(lon: float, lat: float, ring: object) -> bool:
    if not isinstance(ring, list) or len(ring) < 3:
        return False
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = float(ring[i][0]), float(ring[i][1])
        xj, yj = float(ring[j][0]), float(ring[j][1])
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _point_in_geometry(lon: float, lat: float, geometry: object) -> bool:
    if not isinstance(geometry, dict):
        return False
    kind = geometry.get("type")
    if kind == "Polygon":
        rings = geometry.get("coordinates") or []
        if not rings:
            return False
        if not _point_in_ring(lon, lat, rings[0]):
            return False
        return not any(
            _point_in_ring(lon, lat, ring)
            for ring in rings[1:]
        )
    if kind == "MultiPolygon":
        polygons = geometry.get("coordinates") or []
        return any(
            _point_in_geometry(lon, lat, {"type": "Polygon", "coordinates": polygon})
            for polygon in polygons
        )
    return False


@lru_cache(maxsize=1)
def _national_province_features() -> list[dict[str, object]]:
    cache_path = _DISTRICT_CACHE_ROOT / "provinces.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return list(payload.get("features", []))
    payload = _download_geojson(
        "https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json"
    )
    features = list(payload.get("features", []))
    _DISTRICT_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )
    return features


def _province_adcode_for_point(lon: float, lat: float) -> str | None:
    for feature in _national_province_features():
        adcode = str(feature.get("properties", {}).get("adcode", ""))
        if adcode and _point_in_geometry(lon, lat, feature.get("geometry")):
            return adcode
    return None


def _district_boundaries_for_province(province_adcode: str) -> dict[str, object]:
    _DISTRICT_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    cache_path = _DISTRICT_CACHE_ROOT / f"district_{province_adcode}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    province = _download_geojson(
        f"https://geo.datav.aliyun.com/areas_v3/bound/{province_adcode}_full.json"
    )
    features = list(province.get("features", []))
    merged: dict[str, object] = {"type": "FeatureCollection", "features": []}
    if any(
        isinstance(f, dict)
        and f.get("properties", {}).get("level") == "district"
        for f in features
    ):
        # Direct-administered municipalities already return district polygons.
        merged["features"] = features
    else:
        for city in features:
            if not isinstance(city, dict):
                continue
            city_code = str(city.get("properties", {}).get("adcode", ""))
            if not city_code:
                continue
            try:
                city_data = _download_geojson(
                    f"https://geo.datav.aliyun.com/areas_v3/bound/{city_code}_full.json"
                )
                merged["features"].extend(city_data.get("features", []))
            except Exception:
                merged["features"].append(city)
    cache_path.write_text(
        json.dumps(merged, ensure_ascii=False),
        encoding="utf-8",
    )
    return merged


@app.get("/api/v1/stations/district-boundaries")
async def station_district_boundaries(
    lon: float = Query(ge=-180, le=180),
    lat: float = Query(ge=-90, le=90),
) -> dict[str, object]:
    def resolve() -> dict[str, object] | None:
        adcode = _province_adcode_for_point(lon, lat)
        if adcode is None:
            return None
        boundaries = _district_boundaries_for_province(adcode)
        return {
            "province_adcode": adcode,
            "province_name": PROVINCE_ADCODE_NAMES.get(adcode, ""),
            "boundaries": boundaries,
        }

    payload = await asyncio.to_thread(resolve)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail="Point is outside China's land boundaries",
        )
    return payload


def _province_geojson_name(name: str) -> str:
    special = {
        "北京": "北京市",
        "天津": "天津市",
        "上海": "上海市",
        "重庆": "重庆市",
        "内蒙古": "内蒙古自治区",
        "广西": "广西壮族自治区",
        "西藏": "西藏自治区",
        "宁夏": "宁夏回族自治区",
        "新疆": "新疆维吾尔自治区",
    }
    return special.get(name, f"{name}省")


def _collect_geojson_coordinates(
    value: object,
    output: list[tuple[float, float]],
) -> None:
    if (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        output.append((float(value[0]), float(value[1])))
        return
    if isinstance(value, list):
        for item in value:
            _collect_geojson_coordinates(item, output)


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

    try:
        record = resolve_station(normalized)
        return {
            "id": record.wmo_id,
            "name": record.display_name,
            "latitude": record.latitude,
            "longitude": record.longitude,
        }
    except StationLookupError:
        pass

    # Administrative place names (province/city/district) resolve to the
    # administrative centre, which is a fine anchor for gridded forecasts.
    place = resolve_place(normalized)
    if place is not None:
        return {
            "id": str(place.get("adcode") or normalized),
            "name": str(place["name"]),
            "latitude": float(place["latitude"]),
            "longitude": float(place["longitude"]),
        }
    raise StationLookupError(
        f"找不到“{query}”：可输入国家站号/站名、全国地名（省/市/区县）或“纬度,经度”"
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/brand", StaticFiles(directory=BRAND_DIR), name="brand")
app.mount("/products", StaticFiles(directory=PRODUCT_DATA_DIR), name="products")
app.mount("/previews", StaticFiles(directory=PREVIEW_DATA_DIR), name="previews")
