import io
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager

from .station_registry import StationRecord


@dataclass(frozen=True)
class LegacyPlotResult:
    image_bytes: bytes
    source_url: str
    observation_count: int


def render_legacy_observation_png(
    *,
    station: StationRecord,
    mode: str,
    historical_date: date | None = None,
) -> LegacyPlotResult:
    """Run the original q-weather fetch and plot flow with memory output."""
    from Basic_function import History_ObsStation

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
        date_label = historical_date.strftime("%Y%m%d")
    else:
        raise ValueError("history mode requires a date")

    weather_data = History_ObsStation.getdata(source_url)
    if not weather_data or len(weather_data) < 2:
        raise RuntimeError("原数据源没有返回可绘制的逐小时资料")
    if mode == "history":
        weather_data = [weather_data[0], *reversed(weather_data[1:])]

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
