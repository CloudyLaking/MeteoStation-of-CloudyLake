import unittest
from datetime import datetime, timezone

from meteostation.sounding.diagnostics import (
    apply_surface_correction,
    calculate_sounding_diagnostics,
)
from meteostation.sounding.models import (
    SoundingCorrectionInput,
    SoundingLevel,
    SoundingProfile,
)


class SoundingDiagnosticsTests(unittest.TestCase):
    def test_surface_based_diagnostics_include_virtual_and_parcel_lines(
        self,
    ) -> None:
        valid_at = datetime(2026, 7, 26, tzinfo=timezone.utc)
        rows = [
            (1000, 110, 28, 23, 180, 3),
            (925, 760, 22, 18, 190, 5),
            (850, 1450, 17, 12, 200, 7),
            (700, 3100, 7, 0, 220, 10),
            (500, 5700, -8, -20, 240, 15),
            (300, 9200, -34, -48, 250, 20),
            (200, 11900, -53, -65, 260, 24),
            (100, 16400, -67, -78, 270, 28),
        ]
        levels = [
            SoundingLevel(
                observed_at=valid_at,
                longitude=116.47,
                latitude=39.80,
                pressure_hpa=pressure,
                geopotential_height_m=height,
                temperature_c=temperature,
                dewpoint_c=dewpoint,
                wind_direction_deg=direction,
                wind_speed_ms=speed,
            )
            for pressure, height, temperature, dewpoint, direction, speed in rows
        ]
        profile = SoundingProfile(
            station_id="54511",
            valid_at=valid_at,
            source="test",
            source_url="https://example.test",
            fetched_at=valid_at,
            cache_status="hit",
            level_count=len(levels),
            surface_pressure_hpa=1000,
            top_pressure_hpa=100,
            station_longitude=116.47,
            station_latitude=39.80,
            levels=levels,
        )

        diagnostics = calculate_sounding_diagnostics(profile)

        self.assertEqual(len(diagnostics.levels), len(levels))
        self.assertIsNotNone(diagnostics.lcl_pressure_hpa)
        self.assertIsNotNone(diagnostics.cape_j_kg)
        self.assertIsNotNone(diagnostics.cin_j_kg)
        self.assertGreater(
            diagnostics.levels[0].virtual_temperature_c,
            rows[0][2],
        )
        self.assertLess(
            diagnostics.levels[0].wet_bulb_temperature_c,
            rows[0][2],
        )
        self.assertIsNotNone(diagnostics.mixed_layer_cape_j_kg)
        self.assertIsNotNone(diagnostics.most_unstable_cape_j_kg)
        self.assertIsNotNone(diagnostics.dcape_j_kg)
        self.assertIsNotNone(diagnostics.lfc_pressure_hpa)
        self.assertIsNotNone(diagnostics.equilibrium_level_pressure_hpa)
        self.assertIsNotNone(diagnostics.lcl_height_agl_m)
        self.assertIsNotNone(diagnostics.lfc_height_agl_m)
        self.assertIsNotNone(diagnostics.equilibrium_level_height_agl_m)
        self.assertIsNotNone(diagnostics.precipitable_water_mm)
        self.assertAlmostEqual(diagnostics.k_index_c, 30.0, places=1)
        self.assertAlmostEqual(diagnostics.total_totals_index, 45.0, places=1)
        self.assertIsNotNone(diagnostics.sweat_index)
        self.assertIsNotNone(diagnostics.freezing_level_pressure_hpa)
        self.assertIsNotNone(diagnostics.bulk_shear_0_1km_ms)
        self.assertIsNotNone(diagnostics.bulk_shear_0_3km_ms)
        self.assertIsNotNone(diagnostics.bulk_shear_0_6km_ms)
        self.assertIsNotNone(
            diagnostics.storm_relative_helicity_0_1km_m2_s2
        )
        self.assertIsNotNone(
            diagnostics.storm_relative_helicity_0_3km_m2_s2
        )
        self.assertIsNotNone(diagnostics.bunkers_right_motion_u_ms)
        self.assertIsNotNone(diagnostics.bunkers_left_motion_u_ms)
        self.assertIsNotNone(diagnostics.critical_angle_deg)
        self.assertIsNotNone(diagnostics.significant_tornado_fixed)
        self.assertIsNotNone(diagnostics.lapse_rate_700_500_c_km)

        correction = SoundingCorrectionInput(
            pressure_hpa=1005,
            temperature_c=30,
            dewpoint_c=24,
            source_label="test",
        )
        corrected = apply_surface_correction(profile, correction)
        self.assertEqual(profile.surface_pressure_hpa, 1000)
        self.assertEqual(corrected.surface_pressure_hpa, 1005)
        self.assertEqual(corrected.cache_status, "corrected")
        self.assertEqual(corrected.levels[0].temperature_c, 30)
