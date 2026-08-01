from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from .models import RealtimeObservation


class QWeatherError(RuntimeError):
    pass


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
    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            trust_env=False,
            headers={
                "User-Agent": (
                    "CloudyLake-Observatory/2.1.1 "
                    "(https://meteostation.top)"
                )
            },
        ) as client:
            response = await client.get(source_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise QWeatherError(f"逐小时资料暂时无法读取：{exc}") from exc
    return parse_qweather_hourly_html(
        response.content.decode("utf-8", errors="replace"),
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
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            trust_env=False,
            headers={
                "User-Agent": (
                    "CloudyLake-Observatory/2.1.1 "
                    "(https://meteostation.top)"
                )
            },
        ) as client:
            response = await client.get(source_url)
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
