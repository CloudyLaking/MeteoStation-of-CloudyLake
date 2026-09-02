from __future__ import annotations

import calendar
import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .models import CycloneMarker, WeatherMapDomain


NRL_ATCF_ACTIVITY_URL = (
    "https://science.nrlmry.navy.mil/atcf/index1.html"
)
NMC_TYPHOON_API_ROOT = "https://typhoon.nmc.cn/weatherservice/typhoon/jsons"
JTWC_UCAR_BDECK_DIRECTORY = (
    "https://hurricanes.ral.ucar.edu/repository/data/"
    "bdecks_open/{year}/"
)
STORM_PATTERN = re.compile(
    r"SUBJ:\s+.+?\b(?P<id>\d{2}[A-Z])\s+\((?P<name>[^)]+)\)",
    re.IGNORECASE,
)
POSITION_PATTERN = re.compile(
    r"(?P<time>\d{6}Z)\s+---(?:\s+NEAR)?\s+"
    r"(?P<latitude>\d+(?:\.\d+)?)(?P<latitude_hemisphere>[NS])\s+"
    r"(?P<longitude>\d+(?:\.\d+)?)(?P<longitude_hemisphere>[EW])",
    re.IGNORECASE,
)
WIND_PATTERN = re.compile(
    r"MAX SUSTAINED WINDS\s*-\s*(?P<wind>\d+)\s*KT",
    re.IGNORECASE,
)
PRESSURE_PATTERN = re.compile(
    r"MINIMUM CENTRAL PRESSURE AT \d{6}Z IS "
    r"(?P<pressure>\d+)\s*MB",
    re.IGNORECASE,
)


class NrlCycloneUnavailable(RuntimeError):
    """Raised when the NRL ATCF activity page cannot be read."""


class NmcCycloneUnavailable(RuntimeError):
    """Raised when the official CMA/NMC typhoon feed cannot be read."""


class JtwcCycloneUnavailable(RuntimeError):
    """Raised when the JTWC operational best-track mirror cannot be read."""


def fetch_jtwc_tropical_cyclones(
    *,
    valid_at: datetime,
    domain: WeatherMapDomain,
    archive_directory: Path | None = None,
    timeout_seconds: float = 20,
) -> list[CycloneMarker]:
    """Read JTWC operational best tracks from UCAR's resilient TCGP mirror.

    TCGP constructs these open b-decks from the JTWC tcvitals delivered to
    NOAA/NCEP. Only storms with an analysis within six hours of the requested
    map time are returned, so old invests cannot linger on a current chart.
    """
    directory_url = JTWC_UCAR_BDECK_DIRECTORY.format(year=valid_at.year)
    headers = {
        "User-Agent": (
            "CloudyLake-Observatory/2.0 "
            "(meteostation.top JTWC ATCF collector)"
        )
    }
    try:
        response = requests.get(
            directory_url,
            timeout=timeout_seconds,
            headers=headers,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise JtwcCycloneUnavailable(
            f"JTWC/UCAR b-deck directory unavailable: {exc}"
        ) from exc
    soup = BeautifulSoup(response.text, "html.parser")
    filenames: list[str] = []
    pattern = re.compile(rf"^bwp\d{{2}}{valid_at.year}\.dat$", re.IGNORECASE)
    for link in soup.find_all("a", href=True):
        filename = Path(str(link["href"])).name
        if pattern.fullmatch(filename) and filename not in filenames:
            filenames.append(filename)
    if not filenames:
        raise JtwcCycloneUnavailable("JTWC/UCAR directory listed no WP b-decks")

    def retrieve(filename: str) -> tuple[str, str, str]:
        source_url = urljoin(directory_url, filename)
        file_response = requests.get(
            source_url,
            timeout=timeout_seconds,
            headers=headers,
        )
        file_response.raise_for_status()
        return filename, source_url, file_response.text

    markers: list[CycloneMarker] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(retrieve, filename) for filename in filenames]
        for future in as_completed(futures):
            try:
                filename, source_url, bdeck_text = future.result()
            except requests.RequestException:
                failures += 1
                continue
            marker = parse_jtwc_bdeck(
                bdeck_text,
                valid_at=valid_at,
                source_url=source_url,
            )
            if marker is None or not _marker_in_domain(marker, domain):
                continue
            markers.append(marker)
            if archive_directory is not None:
                _archive_text(
                    Path(archive_directory) / f"jtwc-{filename}",
                    bdeck_text,
                )
    if not markers and failures == len(filenames):
        raise JtwcCycloneUnavailable("all JTWC/UCAR b-deck downloads failed")
    markers.sort(key=lambda marker: marker.id)
    return markers


def parse_jtwc_bdeck(
    bdeck_text: str,
    *,
    valid_at: datetime,
    source_url: str,
) -> CycloneMarker | None:
    """Parse one JTWC ATCF b-deck at the analysis nearest ``valid_at``."""
    candidates: list[tuple[float, datetime, list[str]]] = []
    for row in csv.reader(bdeck_text.splitlines(), skipinitialspace=True):
        fields = [item.strip() for item in row]
        if len(fields) < 28 or fields[0].upper() != "WP":
            continue
        if fields[4].upper() != "BEST":
            continue
        try:
            point_time = datetime.strptime(fields[2], "%Y%m%d%H").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        candidates.append(
            (abs((point_time - valid_at).total_seconds()), point_time, fields)
        )
    if not candidates:
        return None
    distance, point_time, fields = min(candidates, key=lambda item: item[0])
    if distance > 6 * 3600:
        return None
    try:
        latitude = _signed_atcf_coordinate(fields[6])
        longitude = _signed_atcf_coordinate(fields[7])
        wind_knots = float(fields[8])
        pressure = float(fields[9])
    except (ValueError, IndexError):
        return None
    storm_number = fields[1].zfill(2)
    name = fields[27].upper() or None
    return CycloneMarker(
        id=f"{storm_number}W",
        kind="tropical",
        valid_at=point_time,
        latitude=latitude,
        longitude=longitude,
        name=name,
        central_pressure_hpa=pressure if pressure > 0 else None,
        maximum_wind_ms=round(wind_knots * 0.514444, 1),
        source=(
            "JTWC operational best track via UCAR TCGP mirror · "
            f"{source_url}"
        ),
        confidence="high",
    )


def fetch_nmc_tropical_cyclones(
    *,
    valid_at: datetime,
    domain: WeatherMapDomain,
    archive_directory: Path | None = None,
    timeout_seconds: float = 20,
) -> list[CycloneMarker]:
    """Read every active numbered system from the official CMA/NMC feed."""
    headers = {
        "User-Agent": (
            "CloudyLake-Observatory/2.0 "
            "(meteostation.top weather-map collector)"
        )
    }
    try:
        response = requests.get(
            f"{NMC_TYPHOON_API_ROOT}/list_default",
            timeout=timeout_seconds,
            headers=headers,
        )
        response.raise_for_status()
        payload = _decode_jsonp(response.content.decode("utf-8"))
    except (requests.RequestException, UnicodeError, ValueError) as exc:
        raise NmcCycloneUnavailable(
            f"CMA/NMC active-system feed unavailable: {exc}"
        ) from exc
    active = [item for item in payload.get("typhoonList", []) if item[7] == "start"]
    markers: list[CycloneMarker] = []
    for item in active:
        internal_id = str(item[0])
        try:
            detail_response = requests.get(
                f"{NMC_TYPHOON_API_ROOT}/view_{internal_id}",
                timeout=timeout_seconds,
                headers=headers,
            )
            detail_response.raise_for_status()
            detail_text = detail_response.content.decode("utf-8")
        except (requests.RequestException, UnicodeError):
            continue
        if archive_directory is not None:
            _archive_text(
                Path(archive_directory) / f"nmc-{internal_id}.jsonp",
                detail_text,
            )
        marker = parse_nmc_typhoon(detail_text, valid_at=valid_at)
        if marker is not None and _marker_in_domain(marker, domain):
            markers.append(marker)
    return markers


def parse_nmc_typhoon(
    response_text: str,
    *,
    valid_at: datetime,
) -> CycloneMarker | None:
    """Choose the official analysis position nearest the requested map time."""
    payload = _decode_jsonp(response_text)
    storm = payload.get("typhoon")
    if not isinstance(storm, list) or len(storm) < 9:
        return None
    points = storm[8]
    if not isinstance(points, list) or not points:
        return None
    candidates = []
    for point in points:
        if not isinstance(point, list) or len(point) < 8:
            continue
        try:
            point_time = datetime.strptime(str(point[1]), "%Y%m%d%H%M").replace(
                tzinfo=timezone.utc
            )
            longitude = float(point[4])
            latitude = float(point[5])
            pressure = float(point[6]) if point[6] is not None else None
            wind = float(point[7]) if point[7] is not None else None
        except (TypeError, ValueError):
            continue
        candidates.append(
            (abs((point_time - valid_at).total_seconds()), point_time, longitude,
             latitude, pressure, wind)
        )
    if not candidates:
        return None
    distance, point_time, longitude, latitude, pressure, wind = min(candidates)
    if distance > 6 * 3600:
        return None
    return CycloneMarker(
        id=str(storm[4]),
        kind="tropical",
        valid_at=point_time,
        latitude=latitude,
        longitude=longitude,
        name=str(storm[1]).upper(),
        central_pressure_hpa=pressure,
        maximum_wind_ms=wind,
        source="CMA National Meteorological Centre typhoon analysis",
        confidence="high",
    )


def _decode_jsonp(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("invalid NMC typhoon JSONP response")
    payload = json.loads(text[start:end + 1])
    if not isinstance(payload, dict):
        raise ValueError("invalid NMC typhoon payload")
    return payload


def fetch_nrl_tropical_cyclones(
    *,
    valid_at: datetime,
    domain: WeatherMapDomain,
    archive_directory: Path | None = None,
    timeout_seconds: float = 20,
) -> list[CycloneMarker]:
    """Read NRL warnings, falling back to the archived analysis-time files."""
    headers = {
        "User-Agent": (
            "CloudyLake-Observatory/2.0 "
            "(meteostation.top weather-map collector)"
        )
    }
    try:
        activity_response = requests.get(
            NRL_ATCF_ACTIVITY_URL,
            timeout=timeout_seconds,
            headers=headers,
        )
        activity_response.raise_for_status()
    except requests.RequestException as exc:
        archived_markers = load_archived_nrl_tropical_cyclones(
            valid_at=valid_at,
            domain=domain,
            archive_directory=archive_directory,
        )
        if archived_markers:
            return archived_markers
        raise NrlCycloneUnavailable(
            f"NRL ATCF activity page unavailable: {exc}"
        ) from exc

    if archive_directory is not None:
        _archive_text(
            Path(archive_directory) / "nrl-atcf-activity.html",
            activity_response.text,
        )
    soup = BeautifulSoup(activity_response.text, "html.parser")
    warning_urls = []
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        if not href.lower().endswith(".wrn"):
            continue
        url = urljoin(NRL_ATCF_ACTIVITY_URL, href)
        if url not in warning_urls:
            warning_urls.append(url)

    markers: list[CycloneMarker] = []
    for warning_url in warning_urls:
        try:
            warning_response = requests.get(
                warning_url,
                timeout=timeout_seconds,
                headers=headers,
            )
            warning_response.raise_for_status()
        except requests.RequestException:
            continue
        warning_text = warning_response.text
        if archive_directory is not None:
            filename = Path(warning_url).name
            _archive_text(
                Path(archive_directory) / filename,
                warning_text,
            )
        marker = parse_nrl_warning(
            warning_text,
            valid_at=valid_at,
            source_url=warning_url,
        )
        if marker is None:
            continue
        if _marker_in_domain(marker, domain):
            markers.append(marker)
    if markers:
        return markers
    return load_archived_nrl_tropical_cyclones(
        valid_at=valid_at,
        domain=domain,
        archive_directory=archive_directory,
    )


def load_archived_nrl_tropical_cyclones(
    *,
    valid_at: datetime,
    domain: WeatherMapDomain,
    archive_directory: Path | None,
) -> list[CycloneMarker]:
    """Load previously archived NRL warning files for an offline rerender."""
    if archive_directory is None:
        return []
    archive_path = Path(archive_directory)
    if not archive_path.is_dir():
        return []
    markers: list[CycloneMarker] = []
    seen_ids: set[str] = set()
    for warning_path in sorted(archive_path.glob("*.wrn")):
        try:
            warning_text = warning_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue
        source_url = urljoin(
            NRL_ATCF_ACTIVITY_URL,
            f"docs/current_storms/{warning_path.name}",
        )
        marker = parse_nrl_warning(
            warning_text,
            valid_at=valid_at,
            source_url=source_url,
        )
        if marker is None or marker.id in seen_ids:
            continue
        if not _marker_in_domain(marker, domain):
            continue
        markers.append(marker)
        seen_ids.add(marker.id)
    return markers


def parse_nrl_warning(
    warning_text: str,
    *,
    valid_at: datetime,
    source_url: str,
) -> CycloneMarker | None:
    """Parse one ATCF warning and choose the point nearest valid_at."""
    storm_match = STORM_PATTERN.search(warning_text)
    if storm_match is None:
        return None
    position_matches = list(POSITION_PATTERN.finditer(warning_text))
    candidates: list[
        tuple[float, datetime, float, float, float | None]
    ] = []
    for index, match in enumerate(position_matches):
        point_time = _resolve_day_time(
            match.group("time"),
            reference=valid_at,
        )
        latitude = _signed_coordinate(
            match.group("latitude"),
            match.group("latitude_hemisphere"),
        )
        longitude = _signed_coordinate(
            match.group("longitude"),
            match.group("longitude_hemisphere"),
        )
        section_end = (
            position_matches[index + 1].start()
            if index + 1 < len(position_matches)
            else len(warning_text)
        )
        section = warning_text[match.end():section_end]
        wind_match = WIND_PATTERN.search(section)
        maximum_wind_ms = (
            round(float(wind_match.group("wind")) * 0.514444, 1)
            if wind_match
            else None
        )
        time_distance = abs(
            (point_time - valid_at).total_seconds()
        )
        candidates.append(
            (
                time_distance,
                point_time,
                latitude,
                longitude,
                maximum_wind_ms,
            )
        )
    if not candidates:
        return None
    (
        time_distance,
        point_time,
        latitude,
        longitude,
        maximum_wind_ms,
    ) = min(candidates)
    if time_distance > 6 * 3600:
        return None
    pressure_match = PRESSURE_PATTERN.search(warning_text)
    pressure = (
        float(pressure_match.group("pressure"))
        if pressure_match and point_time == min(
            candidate[1] for candidate in candidates
        )
        else None
    )
    return CycloneMarker(
        id=storm_match.group("id").upper(),
        kind="tropical",
        valid_at=point_time,
        latitude=latitude,
        longitude=longitude,
        name=storm_match.group("name").upper(),
        central_pressure_hpa=pressure,
        maximum_wind_ms=maximum_wind_ms,
        source=f"NRL ATCF warning mirror · {source_url}",
        confidence="high",
    )


def _resolve_day_time(
    token: str,
    *,
    reference: datetime,
) -> datetime:
    day = int(token[0:2])
    hour = int(token[2:4])
    minute = int(token[4:6])
    candidates: list[datetime] = []
    for month_offset in (-1, 0, 1):
        month_index = reference.year * 12 + reference.month - 1 + month_offset
        year, zero_based_month = divmod(month_index, 12)
        month = zero_based_month + 1
        if day > calendar.monthrange(year, month)[1]:
            continue
        candidates.append(
            datetime(
                year,
                month,
                day,
                hour,
                minute,
                tzinfo=timezone.utc,
            )
        )
    return min(
        candidates,
        key=lambda value: abs(
            (value - reference).total_seconds()
        ),
    )


def _signed_coordinate(value: str, hemisphere: str) -> float:
    coordinate = float(value)
    if hemisphere.upper() in {"S", "W"}:
        coordinate *= -1
    return coordinate


def _signed_atcf_coordinate(token: str) -> float:
    value = token.strip().upper()
    if len(value) < 2 or value[-1] not in {"N", "S", "E", "W"}:
        raise ValueError(f"invalid ATCF coordinate: {token}")
    coordinate = float(value[:-1]) / 10.0
    if value[-1] in {"S", "W"}:
        coordinate *= -1
    return coordinate


def _marker_in_domain(
    marker: CycloneMarker,
    domain: WeatherMapDomain,
) -> bool:
    return (
        domain.west <= marker.longitude <= domain.east
        and domain.south <= marker.latitude <= domain.north
    )


def _archive_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
