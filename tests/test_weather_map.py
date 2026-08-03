import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import requests
import xarray as xr
from PIL import Image

import meteostation.weather_map.basemap as basemap_module

from meteostation.weather_map import (
    WeatherGrid,
    WeatherMapCatalog,
    build_tianditu_wmts_url,
    build_weather_map_plan,
    detect_height_axes,
    detect_low_pressure_centres,
    detect_high_pressure_centres,
    detect_pressure_level_centres,
    detect_surface_fronts,
    fetch_nrl_tropical_cyclones,
    load_tianditu_basemap,
    load_geojson_boundary,
    load_era5_height_climatology,
    parse_nrl_warning,
    read_preview_catalog,
    render_weather_map_preview,
    smooth_field,
    update_preview_catalog,
)


class WeatherMapCatalogTests(unittest.TestCase):
    def test_configuration_and_empty_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "weather_map.json"
            catalog = root / "catalog.json"
            config.write_text(
                json.dumps(
                    {
                        "version": "V2.0.1",
                        "region": "china-and-neighbours",
                        "cycles": ["00", "12"],
                        "domain": {
                            "west": 70,
                            "east": 145,
                            "south": 15,
                            "north": 60,
                            "resolution_degrees": 0.25,
                            "projection": "plate-carree",
                        },
                        "base_map": {"status": "pending"},
                        "input_pipeline": {
                            "source": "ECMWF Open Data",
                            "model": "ifs",
                            "resolution": "0p25",
                            "stream": "oper",
                            "type": "fc",
                            "step_hours": 0,
                        },
                        "analysis_method": {"background": "ECMWF"},
                        "layers": [
                            {
                                "id": "500",
                                "label": "500 hPa",
                                "description": "test",
                                "status": "pipeline-ready",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            service = WeatherMapCatalog(
                config_path=config,
                catalog_path=catalog,
            )

            self.assertEqual(service.configuration().layers[0].id, "500")
            self.assertEqual(
                service.products(
                    valid_date=date(2026, 7, 26),
                    cycle="00",
                    layer_id="500",
                ),
                [],
            )
            jobs = service.jobs(
                valid_date=date(2026, 7, 26),
                cycle="00",
            )
            self.assertEqual(jobs[0].status, "waiting-input")
            self.assertIn("ecmwf-input", jobs[0].blockers)

            plan = build_weather_map_plan(
                configuration=service.configuration(),
                valid_date=date(2026, 7, 26),
                cycle="00",
                raw_data_root=root / "raw",
            )
            self.assertEqual(plan.status, "waiting-input")
            self.assertEqual(
                [request.id for request in plan.requests],
                [
                    "ecmwf-surface",
                    "ecmwf-pressure",
                    "ecmwf-tropical-cyclone-tracks",
                ],
            )
            self.assertEqual(
                plan.requests[1].levelist,
                [850, 500, 200],
            )
            self.assertIn("gh", plan.requests[1].parameters)
            self.assertIn("ecmwf-input", plan.blockers)

    def test_plan_becomes_ready_when_required_inputs_are_archived(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "weather_map.json"
            config_path.write_text(
                json.dumps(
                    {
                        "version": "V2.0.1",
                        "region": "china-and-neighbours",
                        "cycles": ["00", "12"],
                        "domain": {
                            "west": 70,
                            "east": 145,
                            "south": 15,
                            "north": 60,
                            "resolution_degrees": 0.25,
                            "projection": "plate-carree",
                        },
                        "base_map": {
                            "status": "ready",
                            "source": "approved-map",
                            "review_number": "test",
                            "publication_allowed": True,
                        },
                        "input_pipeline": {
                            "source": "ECMWF Open Data",
                            "model": "ifs",
                            "resolution": "0p25",
                            "stream": "oper",
                            "type": "fc",
                            "step_hours": 0,
                        },
                        "analysis_method": {"background": "ECMWF"},
                        "layers": [],
                    }
                ),
                encoding="utf-8",
            )
            service = WeatherMapCatalog(
                config_path=config_path,
                catalog_path=root / "catalog.json",
            )
            initial = build_weather_map_plan(
                configuration=service.configuration(),
                valid_date=date(2026, 7, 26),
                cycle="12",
                raw_data_root=root / "raw",
            )
            for request in initial.requests:
                if not request.required:
                    continue
                target = root / "raw" / request.target_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"grib")

            ready = build_weather_map_plan(
                configuration=service.configuration(),
                valid_date=date(2026, 7, 26),
                cycle="12",
                raw_data_root=root / "raw",
            )
            self.assertEqual(ready.status, "ready-for-analysis")
            self.assertEqual(ready.missing_required_inputs, [])

    def test_synoptic_smoothing_reduces_grid_scale_noise(self) -> None:
        source = np.zeros((41, 41))
        source[::2, ::2] = 10
        source[1::2, 1::2] = -10
        smoothed = smooth_field(
            source,
            sigma_gridpoints=2.0,
        )
        roughness_before = np.mean(np.abs(np.diff(source, axis=1)))
        roughness_after = np.mean(np.abs(np.diff(smoothed, axis=1)))
        self.assertLess(roughness_after, roughness_before * 0.2)

    def test_era5_height_climatology_is_averaged_and_interpolated(
        self,
    ) -> None:
        longitude = np.array([100.0, 101.0])
        latitude = np.array([30.0, 31.0])
        geopotential = np.stack(
            [
                np.full((2, 2), 5_700 * 9.80665),
                np.full((2, 2), 5_800 * 9.80665),
            ]
        )
        dataset = xr.Dataset(
            {
                "z": (
                    ("valid_time", "latitude", "longitude"),
                    geopotential,
                )
            },
            coords={
                "valid_time": np.array(
                    ["1991-07-01", "1992-07-01"],
                    dtype="datetime64[ns]",
                ),
                "latitude": latitude,
                "longitude": longitude,
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "climatology.nc"
            dataset.to_netcdf(path)
            climatology = load_era5_height_climatology(
                path,
                longitude=longitude,
                latitude=latitude,
                month=7,
            )
        np.testing.assert_allclose(
            climatology.values_gpm,
            5_750,
            atol=0.01,
        )

    def test_nrl_warning_position_is_selected_for_analysis_time(self) -> None:
        warning = """
SUBJ:  TYPHOON 11W (NOUL) WARNING NR 008
WARNING POSITION:
250000Z --- NEAR 20.8N 118.3E
MAX SUSTAINED WINDS - 070 KT, GUSTS 085 KT
24 HRS, VALID AT:
260000Z --- 23.4N 115.0E
MAX SUSTAINED WINDS - 070 KT, GUSTS 085 KT
MINIMUM CENTRAL PRESSURE AT 250000Z IS 980 MB.
"""
        marker = parse_nrl_warning(
            warning,
            valid_at=datetime(
                2026,
                7,
                26,
                tzinfo=timezone.utc,
            ),
            source_url="https://example.invalid/wp112026.wrn",
        )
        self.assertIsNotNone(marker)
        assert marker is not None
        self.assertEqual(marker.id, "11W")
        self.assertEqual(marker.name, "NOUL")
        self.assertEqual(marker.latitude, 23.4)
        self.assertEqual(marker.longitude, 115.0)
        self.assertAlmostEqual(marker.maximum_wind_ms or 0, 36.0, delta=0.1)

    def test_nrl_fetch_uses_archived_warning_when_network_fails(self) -> None:
        warning = """
SUBJ:  TYPHOON 11W (NOUL) WARNING NR 008
WARNING POSITION:
260000Z --- NEAR 23.4N 115.0E
MAX SUSTAINED WINDS - 070 KT, GUSTS 085 KT
MINIMUM CENTRAL PRESSURE AT 260000Z IS 980 MB.
"""
        configuration = WeatherMapCatalog(
            config_path=Path("config/weather_map.json"),
            catalog_path=Path("unused.json"),
        ).configuration()
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)
            (archive / "wp112026.wrn").write_text(
                warning,
                encoding="utf-8",
            )
            with patch(
                "meteostation.weather_map.cyclones.requests.get",
                side_effect=requests.ConnectionError("offline"),
            ):
                markers = fetch_nrl_tropical_cyclones(
                    valid_at=datetime(
                        2026,
                        7,
                        26,
                        tzinfo=timezone.utc,
                    ),
                    domain=configuration.domain,
                    archive_directory=archive,
                )
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0].id, "11W")
        self.assertEqual(markers[0].name, "NOUL")

    def test_tianditu_wmts_request_uses_configured_official_layers(
        self,
    ) -> None:
        url = build_tianditu_wmts_url(
            layer="vec_w",
            tile_matrix=4,
            tile_row=6,
            tile_column=12,
            token="domain-restricted-token",
            server=3,
        )
        self.assertTrue(
            url.startswith(
                "https://t3.tianditu.gov.cn/vec_w/wmts?"
            )
        )
        self.assertIn("LAYER=vec", url)
        self.assertIn("TILEMATRIXSET=w", url)
        self.assertIn("tk=domain-restricted-token", url)
        boundary_url = build_tianditu_wmts_url(
            layer="ibo_w",
            tile_matrix=5,
            tile_row=10,
            tile_column=26,
            token="domain-restricted-token",
        )
        self.assertIn("LAYER=ibo", boundary_url)

    def test_tianditu_tiles_are_warped_to_weather_map_domain(self) -> None:
        configuration = WeatherMapCatalog(
            config_path=Path("config/weather_map.json"),
            catalog_path=Path("unused.json"),
        ).configuration()
        tile = Image.new("RGBA", (256, 256), (80, 160, 150, 255))
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                basemap_module,
                "_load_tile",
                return_value=tile,
            ):
                base_map = load_tianditu_basemap(
                    domain=configuration.domain,
                    token="domain-restricted-token",
                    cache_directory=Path(directory),
                    zoom=3,
                    output_width=100,
                )
        self.assertEqual(base_map.vector.shape, (60, 100, 4))
        self.assertEqual(base_map.boundaries.shape, (60, 100, 4))
        self.assertEqual(
            base_map.extent,
            (70.0, 145.0, 15.0, 60.0),
        )

    def test_local_tianditu_province_boundary_is_valid(self) -> None:
        boundary = load_geojson_boundary(
            Path("中国_省.geojson"),
            source="国家地理信息公共服务平台（天地图）",
        )
        self.assertEqual(boundary.feature_count, 42)
        self.assertTrue(boundary.crs.endswith("4490"))
        self.assertGreater(len(boundary.province_lines), 30)
        self.assertGreaterEqual(len(boundary.boundary_lines), 8)
        self.assertEqual(
            boundary.sha256,
            "3af8294f9ad61cc2bf84c1bb7e4bbf86a6336c68d754b699a0e6ddc33ef81486",
        )

    def test_current_china_sounding_station_inventory_is_complete(
        self,
    ) -> None:
        configuration = WeatherMapCatalog(
            config_path=Path("config/weather_map.json"),
            catalog_path=Path("unused.json"),
        ).configuration()
        self.assertEqual(len(configuration.sounding_stations), 88)
        station_ids = {
            station.wmo_id
            for station in configuration.sounding_stations
        }
        self.assertIn("50527", station_ids)
        self.assertIn("57749", station_ids)
        self.assertIn("58362", station_ids)
        self.assertIn("59316", station_ids)
        self.assertIn("59981", station_ids)

    def test_analysis_cycle_uses_previous_ecmwf_cycle_step_12(self) -> None:
        configuration = WeatherMapCatalog(
            config_path=Path("config/weather_map.json"),
            catalog_path=Path("unused.json"),
        ).configuration()
        with tempfile.TemporaryDirectory() as directory:
            plan_00 = build_weather_map_plan(
                configuration=configuration,
                valid_date=date(2026, 7, 26),
                cycle="00",
                raw_data_root=Path(directory),
            )
            plan_12 = build_weather_map_plan(
                configuration=configuration,
                valid_date=date(2026, 7, 26),
                cycle="12",
                raw_data_root=Path(directory),
            )
        surface_00 = plan_00.requests[0]
        surface_12 = plan_12.requests[0]
        self.assertEqual(surface_00.valid_date, date(2026, 7, 25))
        self.assertEqual(surface_00.cycle, "12")
        self.assertEqual(surface_00.step_hours, 12)
        self.assertIn(
            "2026/07/25/ifs_20260725_12_step012",
            surface_00.target_path,
        )
        self.assertEqual(surface_12.valid_date, date(2026, 7, 26))
        self.assertEqual(surface_12.cycle, "00")
        self.assertEqual(surface_12.step_hours, 12)

    def test_objective_low_pressure_centre_is_detected(self) -> None:
        longitude = np.linspace(90, 130, 161)
        latitude = np.linspace(25, 55, 121)
        lon_grid, lat_grid = np.meshgrid(longitude, latitude)
        pressure = (
            1018
            - 24
            * np.exp(
                -(
                    ((lon_grid - 112) / 4) ** 2
                    + ((lat_grid - 42) / 3) ** 2
                )
            )
        )
        grid = WeatherGrid(
            valid_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
            source="synthetic low",
            longitude=longitude,
            latitude=latitude,
            fields={"mslp_hpa": pressure},
        )
        configuration = WeatherMapCatalog(
            config_path=Path("config/weather_map.json"),
            catalog_path=Path("unused.json"),
        ).configuration()
        markers = detect_low_pressure_centres(
            grid,
            domain=configuration.domain,
        )
        self.assertTrue(markers)
        self.assertAlmostEqual(markers[0].longitude, 112, delta=0.5)
        self.assertAlmostEqual(markers[0].latitude, 42, delta=0.5)
        self.assertEqual(markers[0].kind, "low-pressure")

    def test_objective_high_pressure_centre_is_detected(self) -> None:
        longitude = np.linspace(90, 130, 161)
        latitude = np.linspace(20, 55, 141)
        lon_grid, lat_grid = np.meshgrid(longitude, latitude)
        pressure = (
            1005
            + 14
            * np.exp(
                -(
                    ((lon_grid - 112) / 4) ** 2
                    + ((lat_grid - 38) / 3) ** 2
                )
            )
        )
        grid = WeatherGrid(
            valid_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
            source="synthetic high",
            longitude=longitude,
            latitude=latitude,
            fields={"mslp_hpa": pressure},
        )
        configuration = WeatherMapCatalog(
            config_path=Path("config/weather_map.json"),
            catalog_path=Path("unused.json"),
        ).configuration()
        markers = detect_high_pressure_centres(
            grid,
            domain=configuration.domain,
        )
        self.assertTrue(markers)
        self.assertAlmostEqual(markers[0].longitude, 112, delta=0.5)
        self.assertAlmostEqual(markers[0].latitude, 38, delta=0.5)
        self.assertEqual(markers[0].kind, "high-pressure")

    def test_pressure_level_centres_are_detected_from_height_field(self) -> None:
        longitude = np.linspace(90, 130, 161)
        latitude = np.linspace(20, 55, 141)
        lon_grid, lat_grid = np.meshgrid(longitude, latitude)
        height = (
            5800
            - 150
            * np.exp(
                -(
                    ((lon_grid - 106) / 4) ** 2
                    + ((lat_grid - 40) / 3) ** 2
                )
            )
            + 140
            * np.exp(
                -(
                    ((lon_grid - 121) / 4) ** 2
                    + ((lat_grid - 30) / 3) ** 2
                )
            )
        )
        grid = WeatherGrid(
            valid_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
            source="synthetic 500 hPa",
            longitude=longitude,
            latitude=latitude,
            fields={"geopotential_height_500_gpm": height},
        )
        configuration = WeatherMapCatalog(
            config_path=Path("config/weather_map.json"),
            catalog_path=Path("unused.json"),
        ).configuration()
        markers = detect_pressure_level_centres(
            grid,
            domain=configuration.domain,
            pressure_hpa=500,
        )
        kinds = {marker.kind for marker in markers}
        self.assertEqual(kinds, {"low-pressure", "high-pressure"})
        self.assertTrue(
            all(marker.central_height_dam is not None for marker in markers)
        )

    def test_coherent_surface_front_is_detected_and_classified(self) -> None:
        longitude = np.linspace(80, 130, 201)
        latitude = np.linspace(20, 50, 121)
        lon_grid, lat_grid = np.meshgrid(longitude, latitude)
        frontal_axis = 104 + 0.28 * (lat_grid - 35)
        normal_distance = lon_grid - frontal_axis
        temperature = 15 + 9 * np.tanh(normal_distance / 1.5)
        u_wind = 8 - 3 * np.tanh(normal_distance / 2.0)
        v_wind = np.full_like(u_wind, 1.5)
        grid = WeatherGrid(
            valid_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
            source="synthetic baroclinic zone",
            longitude=longitude,
            latitude=latitude,
            fields={
                "temperature_2m_c": temperature,
                "wind_u_10m_ms": u_wind,
                "wind_v_10m_ms": v_wind,
                "surface_pressure_hpa": np.full_like(temperature, 1000),
            },
        )
        configuration = WeatherMapCatalog(
            config_path=Path("config/weather_map.json"),
            catalog_path=Path("unused.json"),
        ).configuration()
        fronts = detect_surface_fronts(
            grid,
            domain=configuration.domain,
        )
        self.assertTrue(fronts)
        self.assertIn("cold-front", {feature.kind for feature in fronts})
        self.assertTrue(
            all(len(feature.coordinates) >= 2 for feature in fronts)
        )

    def test_500_hpa_trough_and_ridge_axes_are_detected(self) -> None:
        longitude = np.linspace(70, 145, 301)
        latitude = np.linspace(15, 60, 181)
        lon_grid, lat_grid = np.meshgrid(longitude, latitude)
        height = (
            5_760
            + 8 * (lat_grid - 35)
            + 105 * np.cos(np.radians((lon_grid - 100) * 12))
        )
        grid = WeatherGrid(
            valid_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
            source="synthetic Rossby wave",
            longitude=longitude,
            latitude=latitude,
            fields={
                "geopotential_height_500_gpm": height,
                "surface_pressure_hpa": np.full_like(height, 1000),
            },
        )
        configuration = WeatherMapCatalog(
            config_path=Path("config/weather_map.json"),
            catalog_path=Path("unused.json"),
        ).configuration()
        axes = detect_height_axes(
            grid,
            domain=configuration.domain,
            pressure_hpa=500,
        )
        self.assertEqual(
            {feature.kind for feature in axes},
            {"trough-axis", "ridge-axis"},
        )
        self.assertTrue(
            all(feature.pressure_hpa == 500 for feature in axes)
        )

    def test_four_field_only_previews_render_to_temporary_directory(
        self,
    ) -> None:
        configuration = WeatherMapCatalog(
            config_path=Path("config/weather_map.json"),
            catalog_path=Path("unused.json"),
        ).configuration()
        longitude = np.linspace(70, 145, 46)
        latitude = np.linspace(15, 60, 31)
        lon_grid, lat_grid = np.meshgrid(longitude, latitude)
        wave = np.sin(np.radians(lon_grid * 3)) * np.cos(
            np.radians(lat_grid * 4)
        )
        fields = {
            "mslp_hpa": 1008 + 14 * wave,
            "temperature_2m_c": 20 + 12 * wave,
            "wind_u_10m_ms": 6 + 4 * wave,
            "wind_v_10m_ms": -2 + 3 * wave,
            "total_column_water_vapour_kg_m2": 35 + 15 * wave,
        }
        for pressure, base_height in ((850, 1500), (500, 5800), (200, 12200)):
            suffix = str(pressure)
            fields[f"geopotential_height_{suffix}_gpm"] = (
                base_height + 180 * wave
            )
            fields[f"temperature_{suffix}_c"] = -5 + 15 * wave
            fields[f"relative_humidity_{suffix}_pct"] = 55 + 35 * wave
            fields[f"wind_u_{suffix}_ms"] = 10 + 8 * wave
            fields[f"wind_v_{suffix}_ms"] = 4 - 6 * wave
            fields[f"vorticity_{suffix}_s1"] = wave * 0.0001
            fields[f"divergence_{suffix}_s1"] = -wave * 0.00005
        fields["geopotential_height_500_climatology_gpm"] = (
            5770 + 80 * wave
        )
        grid = WeatherGrid(
            valid_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
            source="synthetic test field",
            longitude=longitude,
            latitude=latitude,
            fields=fields,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previews = [
                render_weather_map_preview(
                    grid,
                    layer_id=layer,
                    domain=configuration.domain,
                    preview_root=root,
                )
                for layer in ("surface", "850", "500", "200")
            ]
            for preview in previews:
                self.assertTrue(
                    (root / preview.image_url.removeprefix("/previews/")).exists()
                )
                self.assertEqual(
                    preview.publication_status,
                    "development-preview",
                )
                self.assertEqual(preview.base_map_status, "not-included")
                metadata_path = root / preview.metadata_url.removeprefix(
                    "/previews/"
                )
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                self.assertIn(
                    "synoptic_features",
                    metadata["rendering"],
                )
            catalog_path = root / "weather_maps" / "catalog.json"
            update_preview_catalog(catalog_path, previews)
            update_preview_catalog(catalog_path, previews)
            self.assertEqual(
                len(read_preview_catalog(catalog_path)),
                4,
            )
