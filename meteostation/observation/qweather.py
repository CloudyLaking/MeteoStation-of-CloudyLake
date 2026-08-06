import asyncio
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from .models import RealtimeObservation, SurfaceObservation, SurfaceObservationSeries
from .station_registry import StationRecord


class QWeatherError(RuntimeError):
    pass


_QWEATHER_HEADERS = {
    "User-Agent": "CloudyLake-Observatory/2.1.1 (https://meteostation.top)"
}
_qweather_client = httpx.AsyncClient(
    timeout=30,
    follow_redirects=True,
    trust_env=False,
    headers=_QWEATHER_HEADERS,
    limits=httpx.Limits(
        max_connections=8,
        max_keepalive_connections=4,
        keepalive_expiry=300,
    ),
)


async def warm_qweather_connection() -> None:
    """Open the shared upstream connection without delaying web startup."""
    try:
        response = await _qweather_client.get("https://q-weather.info/")
        response.raise_for_status()
    except httpx.HTTPError:
        return


async def close_qweather_client() -> None:
    await _qweather_client.aclose()


async def fetch_qweather_series(
    station: StationRecord,
    *,
    mode: str,
    historical_date: date | None = None,
    history_window: str = "08-08",
) -> SurfaceObservationSeries:
    """Fetch and normalize one 24-hour q-weather table without plotting."""

    china_time = ZoneInfo("Asia/Shanghai")
    if mode == "past24h":
        observation_date = datetime.now(china_time).date()
        source_url = f"https://q-weather.info/weather/{station.wmo_id}/today/"
        html = await _fetch_qweather_html(source_url)
        return parse_qweather_series_html(
            html,
            station=station,
            source_url=source_url,
            observation_date=observation_date,
        )
    elif mode == "history" and historical_date is not None:
        observation_date = historical_date
        window_start, window_end = history_window_bounds(
            historical_date,
            history_window,
        )
        dates = (historical_date, historical_date + timedelta(days=1))
        source_urls = tuple(
            _qweather_daily_url(station.wmo_id, item, china_time)
            for item in dates
        )
        html_pages = await asyncio.gather(
            *(_fetch_qweather_html(url) for url in source_urls)
        )
        daily_series = [
            parse_qweather_series_html(
                html,
                station=station,
                source_url=url,
                observation_date=day,
                limit=None,
            )
            for html, url, day in zip(html_pages, source_urls, dates)
        ]
        merged = {
            observation.observed_at: observation
            for series in daily_series
            for observation in series.observations
            if window_start <= observation.observed_at < window_end
        }
        observations = [merged[key] for key in sorted(merged)]
        if not observations:
            raise QWeatherError("所选 24 小时时段没有可用的逐小时资料")
        return daily_series[0].model_copy(
            update={
                "source_url": source_urls[0],
                "fetched_at": datetime.now(timezone.utc),
                "window_start": window_start,
                "window_end": window_end,
                "window_label": history_window_label(history_window),
                "observations": observations,
            }
        )
    else:
        raise QWeatherError("history mode requires a date")


def history_window_bounds(
    observation_date: date,
    history_window: str,
) -> tuple[datetime, datetime]:
    """Return the selected Beijing-time 24-hour interval as [start, end)."""

    try:
        hour = {"00-00": 0, "08-08": 8, "20-20": 20}[history_window]
    except KeyError as exc:
        raise QWeatherError("history window must be 00-00, 08-08 or 20-20") from exc
    zone = ZoneInfo("Asia/Shanghai")
    start = datetime.combine(observation_date, time(hour=hour), tzinfo=zone)
    return start, start + timedelta(days=1)


def history_window_label(history_window: str) -> str:
    if history_window == "00-00":
        return "00:00—次日 00:00（所选日期全天）"
    if history_window == "08-08":
        return "08:00—次日 08:00"
    if history_window == "20-20":
        return "20:00—次日 20:00"
    raise QWeatherError("history window must be 00-00, 08-08 or 20-20")


def _qweather_daily_url(
    station_id: str,
    requested_date: date,
    china_time: ZoneInfo,
) -> str:
    if requested_date == datetime.now(china_time).date():
        return f"https://q-weather.info/weather/{station_id}/today/"
    return (
        f"https://q-weather.info/weather/{station_id}/history/"
        f"?date={requested_date:%Y-%m-%d}"
    )


def parse_qweather_series_html(
    html: str,
    *,
    station: StationRecord,
    source_url: str,
    observation_date: date,
    limit: int | None = 24,
) -> SurfaceObservationSeries:
    table = BeautifulSoup(html, "html.parser").find("table", class_="border")
    if table is None:
        raise QWeatherError("q-weather 没有返回逐小时资料表")
    rows = [
        [cell.get_text(strip=True) for cell in row.find_all(["th", "td"])]
        for row in table.find_all("tr")
    ]
    if len(rows) < 2:
        raise QWeatherError("q-weather 逐小时资料表为空")
    header = rows[0]
    observations: list[SurfaceObservation] = []
    for values in rows[1:]:
        record = dict(zip(header, values))
        try:
            observed = datetime.strptime(record.get("时次", ""), "%Y-%m-%d %H:%M %z")
        except ValueError:
            continue
        temperature = _number(record.get("瞬时温度"))
        humidity = _number(record.get("相对湿度"))
        observations.append(
            SurfaceObservation(
                observed_at=observed,
                temperature_c=temperature,
                dewpoint_c=_dewpoint(temperature, humidity),
                relative_humidity_pct=humidity,
                station_pressure_hpa=_number(
                    str(record.get("地面气压", "")).strip("()")
                ),
                wind_direction_deg=_leading_number(
                    _first_present(record, "瞬时风向", "2分钟平均风向")
                ),
                wind_speed_ms=_number(
                    _first_present(record, "瞬时风速", "2分钟平均风速")
                ),
                gust_speed_ms=_number(record.get("1小时极大风速")),
                precipitation_1h_mm=_number(record.get("1小时降水")),
                visibility_km=_number(record.get("10分钟平均能见度")),
            )
        )
    observations.sort(key=lambda item: item.observed_at)
    if limit is not None:
        observations = observations[-limit:]
    if not observations:
        raise QWeatherError("q-weather 逐小时资料表没有可解析记录")
    return SurfaceObservationSeries(
        station_id=station.wmo_id,
        station_name=station.display_name,
        station_name_en=station.name,
        latitude=station.latitude,
        longitude=station.longitude,
        elevation_m=station.observation_elevation_m,
        observation_date=observation_date,
        source="q-weather hourly",
        source_url=source_url,
        fetched_at=datetime.now(timezone.utc),
        cache_status="upstream",
        observations=observations,
    )


async def fetch_qweather_hourly(
    station_id: str,
    observed_at: datetime,
) -> RealtimeObservation:
    china_time = ZoneInfo("Asia/Shanghai")
    target = (
        observed_at.replace(tzinfo=china_time)
        if observed_at.tzinfo is None
        else observed_at.astimezone(china_time)
    )
    target = target.replace(minute=0, second=0, microsecond=0)
    today = datetime.now(china_time).date()
    if target.date() == today:
        source_url = f"https://q-weather.info/weather/{station_id}/today/"
    else:
        source_url = (
            f"https://q-weather.info/weather/{station_id}/history/"
            f"?date={target:%Y-%m-%d}"
        )
    html = await _fetch_qweather_html(source_url)
    return parse_qweather_hourly_html(
        html,
        station_id=station_id,
        source_url=source_url,
        target=target,
    )


def parse_qweather_hourly_html(
    html: str,
    *,
    station_id: str,
    source_url: str,
    target: datetime,
) -> RealtimeObservation:
    table = BeautifulSoup(html, "html.parser").find("table", class_="border")
    if table is None:
        raise QWeatherError("q-weather 没有返回逐小时资料表")
    rows = [
        [cell.get_text(strip=True) for cell in row.find_all(["th", "td"])]
        for row in table.find_all("tr")
    ]
    if len(rows) < 2:
        raise QWeatherError("q-weather 逐小时资料表为空")
    header = rows[0]
    for values in rows[1:]:
        record = dict(zip(header, values))
        try:
            observed = datetime.strptime(
                record.get("时次", ""),
                "%Y-%m-%d %H:%M %z",
            )
        except ValueError:
            continue
        if observed.astimezone(target.tzinfo) != target:
            continue
        return RealtimeObservation(
            station_id=station_id,
            source="q-weather hourly",
            source_url=source_url,
            temperature_c=_number(record.get("瞬时温度")),
            relative_humidity_pct=_number(record.get("相对湿度")),
            station_pressure_hpa=_number(
                str(record.get("地面气压", "")).strip("()")
            ),
            wind_direction_deg=_leading_number(record.get("瞬时风向")),
            wind_speed_ms=_number(record.get("瞬时风速")),
            precipitation_1h_mm=_number(record.get("1小时降水")),
            visibility_km=_number(record.get("10分钟平均能见度")),
            observed_at=observed,
        )
    raise QWeatherError(f"找不到 {target:%Y-%m-%d %H:00} 的整点资料")


async def fetch_qweather_realtime(
    station_id: str,
) -> RealtimeObservation:
    source_url = f"https://q-weather.info/api/weather/{station_id}/realtime/"
    try:
        response = await _qweather_client.get(source_url, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        detail = str(exc) or exc.__class__.__name__
        raise QWeatherError(f"实时状态暂时无法读取：{detail}") from exc

    return parse_qweather_realtime(
        payload,
        station_id=station_id,
        source_url=source_url,
    )


async def fetch_qweather_realtime_with_fallback(
    station_id: str,
    *,
    reference_time: datetime | None = None,
) -> RealtimeObservation:
    """Read realtime data, falling back to the previous full Beijing hour.

    q-weather can briefly expose an empty realtime response while its source
    switches at the top of an hour.  The hourly table is independently
    published, so the latest fully completed hour is a deterministic fallback.
    """
    realtime_error: QWeatherError | None = None
    try:
        observation = await fetch_qweather_realtime(station_id)
        core_values = (
            observation.temperature_c,
            observation.relative_humidity_pct,
            observation.station_pressure_hpa,
        )
        if any(value is not None for value in core_values):
            return observation
        realtime_error = QWeatherError("实时响应缺少温度、湿度和气压")
    except QWeatherError as exc:
        realtime_error = exc

    china_time = ZoneInfo("Asia/Shanghai")
    now = reference_time or datetime.now(china_time)
    localized = (
        now.replace(tzinfo=china_time)
        if now.tzinfo is None
        else now.astimezone(china_time)
    )
    previous_hour = localized.replace(
        minute=0,
        second=0,
        microsecond=0,
    ) - timedelta(hours=1)
    try:
        return await fetch_qweather_hourly(station_id, previous_hour)
    except QWeatherError as hourly_error:
        raise QWeatherError(
            f"{realtime_error}；上一整点资料也暂不可用：{hourly_error}"
        ) from hourly_error


def parse_qweather_realtime(
    payload: object,
    *,
    station_id: str,
    source_url: str,
) -> RealtimeObservation:
    if not isinstance(payload, dict):
        raise QWeatherError("q-weather 实时响应不是 JSON 对象")
    realtime = payload.get("realtime")
    if not isinstance(realtime, dict):
        raise QWeatherError("q-weather 没有返回该站实时状态")
    observed_at = _latest_observed_at(realtime.get("time"))
    return RealtimeObservation(
        station_id=station_id,
        source="q-weather realtime",
        source_url=source_url,
        temperature_c=_number(realtime.get("T")),
        relative_humidity_pct=_number(realtime.get("RH")),
        station_pressure_hpa=_number(realtime.get("P")),
        wind_direction_deg=_number(
            realtime.get("WD2m", realtime.get("WD0m"))
        ),
        wind_speed_ms=_number(
            realtime.get("WS2m", realtime.get("WS0m"))
        ),
        precipitation_1h_mm=_number(realtime.get("R1h")),
        visibility_km=_number(
            realtime.get("V10m", realtime.get("V"))
        ),
        observed_at=observed_at,
    )


def _latest_observed_at(value: object) -> datetime | None:
    if not isinstance(value, dict):
        return None
    timestamps: list[datetime] = []
    for raw_timestamp in value.values():
        if not isinstance(raw_timestamp, str):
            continue
        try:
            parsed = datetime.fromisoformat(raw_timestamp)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        timestamps.append(parsed)
    return max(timestamps) if timestamps else None


def _number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _leading_number(value: object) -> float | None:
    if not isinstance(value, str):
        return _number(value)
    return _number(value.split("/", 1)[0])


async def _fetch_qweather_html(source_url: str) -> str:
    try:
        response = await _qweather_client.get(source_url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise QWeatherError(f"逐小时资料暂时无法读取：{exc}") from exc
    return response.content.decode("utf-8", errors="replace")


def _first_present(record: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", "-"):
            return value
    return None


def _dewpoint(temperature_c: float | None, humidity_pct: float | None) -> float | None:
    if temperature_c is None or humidity_pct is None or humidity_pct <= 0:
        return None
    import math

    humidity = min(100.0, humidity_pct)
    gamma = math.log(humidity / 100.0) + 17.625 * temperature_c / (243.04 + temperature_c)
    return round(243.04 * gamma / (17.625 - gamma), 2)
