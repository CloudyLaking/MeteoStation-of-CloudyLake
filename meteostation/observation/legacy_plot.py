import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager

from .models import SurfaceObservationSeries
from .station_registry import StationRecord


@dataclass(frozen=True)
class LegacyPlotResult:
    image_bytes: bytes
    source_url: str
    observation_count: int


def _rows_from_series(series: SurfaceObservationSeries) -> list[list[str]]:
    """Build the legacy row table from an already-normalized series.

    This lets PNG export reuse the structured cache without a second
    upstream request.
    """
    header = [
        "时次",
        "瞬时温度",
        "相对湿度",
        "地面气压",
        "瞬时风向",
        "瞬时风速",
        "1小时降水",
        "10分钟平均能见度",
    ]

    def text(value: float | None) -> str:
        return "-" if value is None else f"{value:g}"

    rows: list[list[str]] = []
    for observation in series.observations:
        rows.append(
            [
                observation.observed_at.strftime("%Y-%m-%d %H:%M"),
                text(observation.temperature_c),
                text(observation.relative_humidity_pct),
                text(observation.station_pressure_hpa),
                text(observation.wind_direction_deg),
                text(observation.wind_speed_ms),
                text(observation.precipitation_1h_mm),
                text(observation.visibility_km),
            ]
        )
    return [header, *rows]


def render_legacy_observation_png(
    *,
    station: StationRecord,
    mode: str,
    historical_date: date | None = None,
    history_window: str = "08-08",
    series: SurfaceObservationSeries | None = None,
) -> LegacyPlotResult:
    """Run the original q-weather fetch and plot flow with memory output.

    When *series* is provided (structured cache), the upstream HTML fetch is
    skipped entirely and the plot reuses the already-normalized observations.
    """
    from Basic_function import History_ObsStation

    if series is not None:
        weather_data = _rows_from_series(series)
        source_url = series.source_url
        if mode == "past24h":
            date_label = f"{datetime.now():%Y%m%d}-today"
        else:
            date_label = (
                f"{historical_date:%Y%m%d}-{history_window}"
                if historical_date is not None
                else f"{series.observation_date:%Y%m%d}"
            )
    else:
        if mode == "past24h":
            source_url = (
                f"https://q-weather.info/weather/{station.wmo_id}/today/"
            )
            date_label = f"{datetime.now():%Y%m%d}-today"
        elif mode == "history" and historical_date is not None:
            source_url = (
                f"https://q-weather.info/weather/{station.wmo_id}/history/"
                f"?date={historical_date:%Y-%m-%d}"
            )
            if history_window not in {"08-08", "20-20"}:
                raise ValueError("history window must be 08-08 or 20-20")
            date_label = f"{historical_date:%Y%m%d}-{history_window}"
        else:
            raise ValueError("history mode requires a date")

        weather_data = History_ObsStation.getdata(source_url)
        if not weather_data or len(weather_data) < 2:
            raise RuntimeError("原数据源没有返回可绘制的逐小时资料")
        if mode == "history":
            next_date = historical_date + timedelta(days=1)
            next_url = (
                f"https://q-weather.info/weather/{station.wmo_id}/history/"
                f"?date={next_date:%Y-%m-%d}"
            )
            next_data = History_ObsStation.getdata(next_url)
            if not next_data or len(next_data) < 2:
                raise RuntimeError("所选 24 小时时段的次日资料暂不可用")
            hour = 8 if history_window == "08-08" else 20
            start = datetime.combine(historical_date, datetime.min.time()).replace(hour=hour)
            end = start + timedelta(days=1)
            time_index = weather_data[0].index("时次")
            rows = [*weather_data[1:], *next_data[1:]]
            filtered_rows = []
            for row in rows:
                try:
                    observed_at = datetime.strptime(row[time_index][:16], "%Y-%m-%d %H:%M")
                except (ValueError, IndexError):
                    continue
                if start <= observed_at < end:
                    filtered_rows.append(row)
            weather_data = [weather_data[0], *reversed(filtered_rows)]
            source_url = f"{source_url} ; {next_url}"

    if len(weather_data) < 2:
        raise RuntimeError("可绘制的逐小时资料不足")

    buffer = io.BytesIO()
    project_font = Path(__file__).resolve().parents[2] / "MiSans VF.ttf"
    original_savefig = plt.savefig
    original_addfont = font_manager.fontManager.addfont

    def savefig_to_memory(_filename: object, *args: object, **kwargs: object) -> None:
        kwargs["format"] = "png"
        original_savefig(buffer, *args, **kwargs)

    def add_project_font(path: str | Path) -> None:
        requested = Path(path)
        original_addfont(
            str(requested if requested.exists() else project_font)
        )

    plt.savefig = savefig_to_memory
    font_manager.fontManager.addfont = add_project_font
    try:
        History_ObsStation.drawdata(
            weather_data,
            station.legacy_fields(),
            date_label,
        )
    finally:
        plt.savefig = original_savefig
        font_manager.fontManager.addfont = original_addfont
        plt.close("all")
    return LegacyPlotResult(
        image_bytes=buffer.getvalue(),
        source_url=source_url,
        observation_count=len(weather_data) - 1,
    )
