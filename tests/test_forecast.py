import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr

from meteostation.forecast import retriever
from meteostation.forecast import collector as forecast_collector
from meteostation.forecast.collector import (
    ForecastCollector,
    ForecastCollectorConfig,
    prune_forecast_cycles,
    recent_forecast_cycles,
)
from meteostation.forecast.fast_store import convert_forecast_grib
from meteostation.ecmwf_mars import mars_model_keywords, mars_point_area
from meteostation.observation.station_registry import resolve_station
from web import app as web_app
from web.app import resolve_forecast_location


def _steps() -> np.ndarray:
    return np.asarray([0, 3], dtype="timedelta64[h]")


def _surface_datasets() -> list[xr.Dataset]:
    coordinates = {
        "step": _steps(),
        "latitude": [31.5, 31.75],
        "longitude": [121.5, 121.75],
    }
    shape = (2, 2, 2)

    def field(value: float, short_name: str) -> xr.DataArray:
        result = xr.DataArray(
            np.full(shape, value),
            dims=("step", "latitude", "longitude"),
            coords=coordinates,
        )
        result.attrs["GRIB_shortName"] = short_name
        return result

    return [
        xr.Dataset(
            {
                "t2m": field(303.15, "2t"),
                "d2m": field(298.15, "2d"),
                "u10": field(5.0, "10u"),
                "v10": field(0.0, "10v"),
                "sp": field(100000.0, "sp"),
                "msl": field(100800.0, "msl"),
                "tp": field(0.002, "tp"),
                "tcc": field(0.75, "tcc"),
            }
        )
    ]


def _pressure_datasets(*, use_specific_humidity: bool = False) -> list[xr.Dataset]:
    coordinates = {
        "step": _steps(),
        "isobaricInhPa": [1000.0, 500.0],
        "latitude": [31.5, 31.75],
        "longitude": [121.5, 121.75],
    }
    shape = (2, 2, 2, 2)

    def field(value: float, short_name: str) -> xr.DataArray:
        result = xr.DataArray(
            np.full(shape, value),
            dims=("step", "isobaricInhPa", "latitude", "longitude"),
            coords=coordinates,
        )
        result.attrs["GRIB_shortName"] = short_name
        return result

    height = field(100.0, "gh")
    height.loc[{"isobaricInhPa": 500.0}] = 5880.0
    humidity = (
        {"q": field(0.004, "q")}
        if use_specific_humidity
        else {"r": field(50.0, "r")}
    )
    return [
        xr.Dataset(
            {
                "gh": height,
                "t": field(283.15, "t"),
                **humidity,
                "u": field(5.0, "u"),
                "v": field(0.0, "v"),
            }
        )
    ]


def test_station_record_exposes_decimal_coordinates() -> None:
    station = resolve_station("58362")
    assert station.latitude == 31.65
    assert station.longitude == 121.75


def test_forecast_pressure_levels_use_all_open_data_native_levels() -> None:
    assert retriever.FORECAST_PRESSURE_LEVELS == [
        1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50,
    ]


def test_mars_point_area_keeps_interpolation_neighbours() -> None:
    assert mars_point_area(31.65, 121.75) == (
        "31.9000/121.5000/31.4000/122.0000"
    )
    assert mars_model_keywords("ifs") == {
        "class": "od",
        "expver": "1",
    }
    assert mars_model_keywords("aifs")["model"] == "aifs-single"


def test_mars_surface_request_uses_full_native_horizon(
    monkeypatch,
    tmp_path,
) -> None:
    requests: list[dict[str, object]] = []

    def fake_retrieve(request, target) -> None:
        requests.append(request)
        target.write_bytes(b"grib")

    monkeypatch.setattr(retriever, "retrieve_mars", fake_retrieve)
    surface, _ = retriever.retrieve_ecmwf_forecast(
        initialized_at=datetime.now(timezone.utc),
        cache_root=tmp_path,
        model="ifs",
        include_pressure=False,
        latitude=31.65,
        longitude=121.75,
        backend="mars",
    )

    assert surface.read_bytes() == b"grib"
    assert requests[0]["step"] == "0/to/144/by/3"
    assert requests[0]["grid"] == "0.25/0.25"
    assert requests[0]["area"] == "31.9000/121.5000/31.4000/122.0000"


def test_atomic_forecast_download_resumes_indexed_ranges(
    monkeypatch,
    tmp_path,
) -> None:
    class FakeClient:
        use_sas_token = False
        verify = True
        session = object()
        source = SimpleNamespace(
            accept_ranges=True,
            accept_multiple_ranges=False,
        )

        def _get_urls(self, request, target, use_index):
            return SimpleNamespace(
                urls=[
                    (
                        "https://example.test/forecast.grib2",
                        ((100, 4), (200, 6)),
                    )
                ]
            )

    target = tmp_path / "forecast.grib2"
    partial = target.with_suffix(".grib2.part")
    continuation = partial.with_suffix(".part.resume")
    partial.write_bytes(b"abc")
    calls: list[object] = []

    def interrupted_download(urls, target, **kwargs):
        calls.append(urls)
        Path(target).write_bytes(b"de")
        raise OSError("connection dropped")

    monkeypatch.setattr(
        retriever,
        "multiurl_download",
        interrupted_download,
    )
    with pytest.raises(OSError):
        retriever._retrieve_atomically(
            FakeClient(),
            request={"param": ["t"]},
            target=target,
        )

    assert partial.read_bytes() == b"abc"
    assert continuation.read_bytes() == b"de"
    assert calls[0][0][1] == ((103, 1), (200, 6))

    def resumed_download(urls, target, **kwargs):
        calls.append(urls)
        Path(target).write_bytes(b"fghij")

    monkeypatch.setattr(
        retriever,
        "multiurl_download",
        resumed_download,
    )
    retriever._retrieve_atomically(
        FakeClient(),
        request={"param": ["t"]},
        target=target,
    )

    assert target.read_bytes() == b"abcdefghij"
    assert not partial.exists()
    assert not continuation.exists()
    assert calls[1][0][1] == ((201, 5),)


def test_forecast_location_accepts_station_name_and_coordinates() -> None:
    station = resolve_forecast_location("宝山")
    coordinates = resolve_forecast_location("31.65, 121.75")

    assert station["id"] == "58362"
    assert coordinates == {
        "id": "31.6500,121.7500",
        "name": "31.65°, 121.75°",
        "latitude": 31.65,
        "longitude": 121.75,
    }


def test_recent_cycles_returns_four_cycles_per_day() -> None:
    cycles = recent_forecast_cycles(
        reference_time=datetime(2026, 7, 27, 13, tzinfo=timezone.utc),
        cycles=["00", "06", "12", "18"],
        count=8,
    )
    assert len(cycles) == 8
    assert cycles[0] == datetime(2026, 7, 27, 12, tzinfo=timezone.utc)
    assert cycles[-1] == datetime(2026, 7, 25, 18, tzinfo=timezone.utc)


def test_latest_cached_cycle_falls_back_to_previous_complete_run(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(web_app, "FORECAST_CACHE_ROOT", tmp_path)
    directory = tmp_path / "ecmwf_forecast" / "ifs" / "2026" / "08" / "02"
    directory.mkdir(parents=True)
    for hour in ("12", "18"):
        (directory / (
            f"ifs_20260802_{hour}z_forecast_surface_144h_3hourly.fast.nc"
        )).write_bytes(b"cached")

    result = web_app._latest_cached_forecast_cycle(
        model="ifs",
        requested_at=datetime(2026, 8, 3, 0, tzinfo=timezone.utc),
        field_type="surface",
    )

    assert result == datetime(2026, 8, 2, 18, tzinfo=timezone.utc)


def test_latest_cached_cycle_can_ignore_an_expired_request(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(web_app, "FORECAST_CACHE_ROOT", tmp_path)
    directory = tmp_path / "ecmwf_forecast" / "ifs" / "2026" / "08" / "09"
    directory.mkdir(parents=True)
    cached = directory / (
        "ifs_20260809_12z_forecast_surface_144h_3hourly.fast.nc"
    )
    cached.write_bytes(b"cached")

    result = web_app._latest_cached_forecast_cycle(
        model="ifs",
        requested_at=None,
        field_type="surface",
    )

    assert result == datetime(2026, 8, 9, 12, tzinfo=timezone.utc)


def test_collector_interleaves_models_for_latest_cycle(
    monkeypatch,
    tmp_path,
) -> None:
    calls: list[tuple[str, datetime]] = []

    def fake_retrieve(*, initialized_at, model, **kwargs):
        calls.append((model, initialized_at))
        model_root = tmp_path / model
        model_root.mkdir()
        surface = model_root / "surface.grib2"
        pressure = model_root / "pressure.grib2"
        surface.write_bytes(b"surface")
        pressure.write_bytes(b"pressure")
        return surface, pressure

    monkeypatch.setattr(
        forecast_collector,
        "retrieve_ecmwf_forecast",
        fake_retrieve,
    )
    monkeypatch.setattr(
        forecast_collector,
        "_cycle_is_complete",
        lambda *args, **kwargs: False,
    )
    collector = ForecastCollector(
        config=ForecastCollectorConfig(
            retain_complete_cycles=1,
            request_spacing_seconds=0,
            minimum_free_disk_gb=2,
            download_reserve_gb=1,
                models=["ifs", "aifs"],
                convert_to_fast_store=False,
            ),
        cache_root=tmp_path,
        state_path=tmp_path / "state.json",
    )
    reference_time = datetime(2026, 7, 27, 13, tzinfo=timezone.utc)

    asyncio.run(collector.run_once(reference_time=reference_time))

    assert calls == [
        ("ifs", datetime(2026, 7, 27, 12, tzinfo=timezone.utc)),
        ("aifs", datetime(2026, 7, 27, 12, tzinfo=timezone.utc)),
    ]


def test_prune_forecast_cycles_keeps_latest_eight(tmp_path) -> None:
    model_root = tmp_path / "ifs"
    for index in range(10):
        initialized = datetime(
            2026, 7, 24, tzinfo=timezone.utc
        ) + timedelta(hours=index * 6)
        directory = (
            model_root
            / f"{initialized:%Y}"
            / f"{initialized:%m}"
            / f"{initialized:%d}"
        )
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"ifs_{initialized:%Y%m%d}_{initialized:%H}z"
        (directory / f"{stem}_forecast_surface_144h_3hourly.grib2").write_bytes(
            b"surface"
        )
        (directory / f"{stem}_forecast_pressure_144h_3hourly.grib2").write_bytes(
            b"pressure"
        )

    removed = prune_forecast_cycles(model_root, keep=8)

    assert len(removed) == 2
    assert len(list(model_root.rglob("*_forecast_surface_144h_3hourly.grib2"))) == 8


def test_extract_surface_forecast_from_cfgrib_datasets(monkeypatch) -> None:
    monkeypatch.setattr(
        "cfgrib.open_datasets",
        lambda _: _surface_datasets(),
    )
    forecast = retriever.extract_surface_forecast(
        Path("unused.grib2"),
        station_id="58362",
        station_name="宝山",
        latitude=31.65,
        longitude=121.75,
        initialized_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
    )

    assert forecast is not None
    assert len(forecast.points) == 2
    assert forecast.points[0].temperature_2m_c == 30.0
    assert forecast.points[0].total_precipitation_mm == 2.0
    assert forecast.points[0].wind_direction_10m_deg == 270


def test_fast_store_round_trip_matches_surface_decoder(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr("cfgrib.open_datasets", lambda _: _surface_datasets())
    source = tmp_path / "ifs_test_surface.grib2"
    source.write_bytes(b"test")
    store = convert_forecast_grib(source, kind="surface")

    forecast = retriever.extract_surface_forecast(
        store,
        station_id="58362",
        station_name="宝山",
        latitude=31.65,
        longitude=121.75,
        initialized_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
    )

    assert forecast is not None
    assert len(forecast.points) == 2
    assert forecast.points[0].temperature_2m_c == 30.0
    assert forecast.points[0].mslp_hpa == 1008.0


def test_fast_store_round_trip_selects_one_sounding_step(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr("cfgrib.open_datasets", lambda _: _pressure_datasets())
    source = tmp_path / "ifs_test_pressure.grib2"
    source.write_bytes(b"test")
    store = convert_forecast_grib(source, kind="pressure")

    soundings = retriever.extract_sounding_forecast(
        store,
        station_id="58362",
        station_name="宝山",
        latitude=31.65,
        longitude=121.75,
        initialized_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
        step_hours=3,
    )

    assert soundings is not None
    assert len(soundings) == 1
    assert soundings[0].step_hours == 3


def test_extract_sounding_keeps_geopotential_height_in_gpm(monkeypatch) -> None:
    monkeypatch.setattr(
        "cfgrib.open_datasets",
        lambda _: _pressure_datasets(),
    )
    soundings = retriever.extract_sounding_forecast(
        Path("unused.grib2"),
        station_id="58362",
        station_name="宝山",
        latitude=31.65,
        longitude=121.75,
        initialized_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
    )

    assert soundings is not None
    assert len(soundings) == 2
    assert [level.pressure_hpa for level in soundings[0].levels] == [
        1000.0,
        500.0,
    ]
    assert soundings[0].levels[0].height_gpm == 100.0
    assert soundings[0].levels[1].height_gpm == 5880.0
    assert soundings[0].levels[0].wind_direction_deg == 270


def test_extract_sounding_selects_step_before_loading(monkeypatch) -> None:
    monkeypatch.setattr(
        "cfgrib.open_datasets",
        lambda _: _pressure_datasets(),
    )
    soundings = retriever.extract_sounding_forecast(
        Path("unused.grib2"),
        station_id="58362",
        station_name="Baoshan",
        latitude=31.65,
        longitude=121.75,
        initialized_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
        step_hours=3,
    )

    assert soundings is not None
    assert len(soundings) == 1
    assert soundings[0].step_hours == 3


def test_extract_aifs_sounding_converts_specific_humidity(monkeypatch) -> None:
    monkeypatch.setattr(
        "cfgrib.open_datasets",
        lambda _: _pressure_datasets(use_specific_humidity=True),
    )
    soundings = retriever.extract_sounding_forecast(
        Path("aifs_unused.grib2"),
        station_id="31.6500,121.7500",
        station_name="31.65°, 121.75°",
        latitude=31.65,
        longitude=121.75,
        initialized_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
    )

    assert soundings is not None
    assert soundings[0].levels[0].relative_humidity_pct is not None
    assert soundings[0].levels[0].dewpoint_c is not None
