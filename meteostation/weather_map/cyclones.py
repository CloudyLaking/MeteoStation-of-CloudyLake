from __future__ import annotations

import calendar
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .models import CycloneMarker, WeatherMapDomain


NRL_ATCF_ACTIVITY_URL = (
    "https://science.nrlmry.navy.mil/atcf/index1.html"
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
