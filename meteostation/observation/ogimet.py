import csv
import io
import math
from datetime import date, datetime, timedelta, timezone

import httpx

from .models import SurfaceObservation, SurfaceObservationSeries
from .station_registry import resolve_station


class OgimetError(RuntimeError):
    pass


async def fetch_ogimet_series(
    *,
    station_id: str,
    mode: str,
    historical_date: date | None = None,
    station_info: dict[str, object] | None = None,
) -> SurfaceObservationSeries:
    begin, end, observation_date = query_interval(
        mode=mode,
        historical_date=historical_date,
    )
    source_url = (
        "https://www.ogimet.com/cgi-bin/getsynop"
        f"?block={station_id}"
        f"&begin={begin:%Y%m%d%H%M}"
        f"&end={end:%Y%m%d%H%M}"
        "&lang=eng&header=yes"
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
        raise OgimetError(f"OGIMET 暂时无法访问：{exc}") from exc

    observations = parse_ogimet_csv(
        response.text,
        station_id=station_id,
    )
    if not observations:
        raise OgimetError("OGIMET 在所选时段没有返回该站 SYNOP")

    info = station_info or {}
    station_name = info.get("display_name") or info.get("name") or station_id
    return SurfaceObservationSeries(
        station_id=station_id,
        station_name=str(station_name),
        station_name_en=str(info.get("name") or ""),
        latitude=float(info.get("latitude", 0.0)),
        longitude=float(info.get("longitude", 0.0)),
        elevation_m=float(info.get("elevation_m", 0.0)),
        observation_date=observation_date,
        source="OGIMET SYNOP",
        source_url=source_url,
        fetched_at=datetime.now(timezone.utc),
        cache_status="not-stored",
        observations=observations,
    )


def query_interval(
    *,
    mode: str,
    historical_date: date | None,
) -> tuple[datetime, datetime, date]:
    if mode == "past24h":
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        return end - timedelta(hours=24), end, end.date()
    if mode != "history" or historical_date is None:
        raise ValueError("历史查询必须提供日期")
    begin = datetime.combine(
        historical_date,
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    return begin, begin + timedelta(days=1) - timedelta(minutes=1), historical_date


def parse_ogimet_csv(
    raw_csv: str,
    *,
    station_id: str,
) -> list[SurfaceObservation]:
    observations: list[SurfaceObservation] = []
    for row in csv.DictReader(io.StringIO(raw_csv)):
        if (row.get("WMO_ID") or "").strip() != station_id:
            continue
        try:
            observed_at = datetime(
                int(row["ANO"]),
                int(row["MES"]),
                int(row["DIA"]),
                int(row["HORA"]),
                int(row["MINUTO"]),
                tzinfo=timezone.utc,
            )
        except (KeyError, TypeError, ValueError):
            continue
        observation = decode_synop(
            row.get("PARTE", ""),
            observed_at=observed_at,
        )
        if observation is not None:
            observations.append(observation)
    observations.sort(key=lambda item: item.observed_at)
    return observations


def _looks_like_visibility(group: str) -> bool:
    """Standard ``ixhVV`` group: i in 0..4, VV numeric in the last two chars."""
    return (
        len(group) == 5
        and group[0] in "01234"
        and group[3:5].isdigit()
    )


def _looks_like_wind(group: str) -> bool:
    """A ``ddff`` group (possibly with a leading ``/``): dd 00..36, ff numeric."""
    if len(group) != 5:
        return False
    dd_source = group[1:3] if group[0] == "/" else group[0:2]
    if not dd_source.isdigit() or not group[3:5].isdigit():
        return False
    return 0 <= int(dd_source) <= 36


def decode_synop(
    report: str,
    *,
    observed_at: datetime,
) -> SurfaceObservation | None:
    groups = report.replace("==", "").split()
    try:
        aaxx_index = groups.index("AAXX")
        wind_unit_code = int(groups[aaxx_index + 1][-1])
        station_index = aaxx_index + 2
    except (ValueError, IndexError):
        return None

    section_end = groups.index("333") if "333" in groups else len(groups)
    body = groups[station_index + 1:section_end]
    section_three = groups[section_end + 1:] if section_end < len(groups) else []

    # Standard reports put visibility then wind right after the id; the rest
    # of section one is decoded by group prefix. Overseas reports (e.g. some
    # Gulf stations) may omit the wind/visibility pair, so those stay None.
    visibility_code = None
    wind_group = None
    semantic_start = 0
    if body and _looks_like_visibility(body[0]):
        visibility_code = body[0][3:5]
        semantic_start = 1
    if len(body) > semantic_start and _looks_like_wind(body[semantic_start]):
        wind_group = body[semantic_start]
        semantic_start += 1
    semantic = body[semantic_start:]

    def find(prefix: str) -> str | None:
        return next(
            (
                group
                for group in semantic
                if len(group) == 5
                and group.startswith(prefix)
                and "/" not in group
            ),
            None,
        )

    temperature = _signed_tenths(find("1"))
    dewpoint = _signed_tenths(find("2"))
    humidity = _relative_humidity(temperature, dewpoint)
    direction, wind_speed = (
        _wind(wind_group, wind_unit_code) if wind_group else (None, None)
    )
    return SurfaceObservation(
        observed_at=observed_at,
        temperature_c=temperature,
        dewpoint_c=dewpoint,
        relative_humidity_pct=humidity,
        station_pressure_hpa=_pressure(find("3")),
        wind_direction_deg=direction,
        wind_speed_ms=wind_speed,
        gust_speed_ms=_gust(section_three, wind_unit_code),
        precipitation_1h_mm=_precipitation(find("6")),
        visibility_km=_visibility(visibility_code),
    )


def to_legacy_weather_table(
    series: SurfaceObservationSeries,
) -> list[list[str]]:
    header = [
        "时次",
        "瞬时温度",
        "相对湿度",
        "地面气压",
        "2分钟平均风向",
        "2分钟平均风速",
        "1小时极大风速",
        "1小时降水",
        "10分钟平均能见度",
    ]
    rows = []
    for item in reversed(series.observations):
        direction = _legacy_wind_direction(item.wind_direction_deg)
        rows.append(
            [
                item.observed_at.strftime("%Y-%m-%d %H:%M +0000"),
                _legacy_number(item.temperature_c),
                _legacy_number(item.relative_humidity_pct),
                _legacy_number(item.station_pressure_hpa),
                direction,
                _legacy_number(item.wind_speed_ms),
                _legacy_number(item.gust_speed_ms),
                _legacy_number(item.precipitation_1h_mm),
                _legacy_number(item.visibility_km),
            ]
        )
    return [header, *rows]


def station_information(station_id: str) -> list[str]:
    return resolve_station(station_id).legacy_fields()


def _first_group(groups: list[str], prefix: str) -> str | None:
    return next(
        (
            group
            for group in groups
            if len(group) == 5
            and group.startswith(prefix)
            and "/" not in group
        ),
        None,
    )


def _signed_tenths(group: str | None) -> float | None:
    if group is None or len(group) != 5 or not group[2:].isdigit():
        return None
    sign = -1 if group[1] == "1" else 1
    return sign * int(group[2:]) / 10


def _pressure(group: str | None) -> float | None:
    if group is None or not group[1:].isdigit():
        return None
    value = int(group[1:])
    if value >= 5000:
        # Pressure below 1000 hPa is coded as (P - 900) * 10, e.g. 994.3 -> 9943.
        return value / 10
    # Pressure at or above 1000 hPa is coded as (P - 1000) * 10, e.g. 1007.3 -> 73.
    return value / 10 + 1000


def _wind(
    group: str,
    wind_unit_code: int,
) -> tuple[float | None, float | None]:
    if len(group) != 5 or not group[1:].isdigit():
        return None, None
    direction_code = int(group[1:3])
    speed_code = int(group[3:5])
    direction = None if direction_code >= 50 else direction_code * 10.0
    speed = speed_code * 0.514444 if wind_unit_code in {3, 4} else float(speed_code)
    return direction, round(speed, 2)


def _gust(groups: list[str], wind_unit_code: int) -> float | None:
    gust_group = next(
        (
            group
            for group in groups
            if len(group) == 5
            and group.startswith(("910", "911"))
            and group[3:].isdigit()
        ),
        None,
    )
    if gust_group is None:
        return None
    speed = int(gust_group[3:])
    if wind_unit_code in {3, 4}:
        speed *= 0.514444
    return round(speed, 2)


def _precipitation(group: str | None) -> float | None:
    if group is None or not group[1:4].isdigit():
        return None
    code = int(group[1:4])
    if code <= 988:
        # 6RRRt: RRR is coded in tenths of a millimetre.
        return code / 10
    if code == 990:
        return 0.0
    if 991 <= code <= 999:
        return (code - 990) / 10
    return None


def _visibility(code: str | None) -> float | None:
    if code is None or not code.isdigit():
        return None
    value = int(code)
    if value <= 50:
        return value / 10
    if value <= 55:
        return float(value - 50)
    if value <= 80:
        return float((value - 50) * 1)
    if value <= 89:
        return float(30 + (value - 80) * 5)
    special = {
        90: 0.04,
        91: 0.05,
        92: 0.2,
        93: 0.5,
        94: 1.0,
        95: 2.0,
        96: 4.0,
        97: 10.0,
        98: 20.0,
        99: 50.0,
    }
    return special.get(value)


def _relative_humidity(
    temperature_c: float | None,
    dewpoint_c: float | None,
) -> float | None:
    if temperature_c is None or dewpoint_c is None:
        return None
    a = 17.625
    b = 243.04
    saturation = math.exp(a * temperature_c / (b + temperature_c))
    vapor = math.exp(a * dewpoint_c / (b + dewpoint_c))
    return round(max(0, min(100, vapor / saturation * 100)), 1)


def _coordinate(value: str) -> float:
    if len(value) < 3:
        return 0.0
    degree_digits = len(value) - 2
    return int(value[:degree_digits]) + int(value[degree_digits:]) / 60


def _legacy_number(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def _legacy_wind_direction(value: float | None) -> str:
    if value is None:
        return "-"
    names = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]
    name = names[round((value % 360) / 22.5) % 16]
    return f"{value:g}/{name}"
