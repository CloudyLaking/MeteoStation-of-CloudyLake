import tempfile
import unittest
import json
from datetime import date, datetime, timezone
from pathlib import Path

from meteostation.sounding.wyoming import (
    WyomingSoundingClient,
    build_wyoming_url,
    parse_wyoming_csv,
    validate_station_id,
)


SAMPLE_CSV = """time,longitude,latitude,pressure_hPa,geopotential height_m,temperature_C,dew point temperature_C,ice point temperature_C,relative humidity_%,humidity wrt ice_%,mixing ratio_g/kg,wind direction_degree,wind speed_m/s
2026-07-25 23:16:20,116.2800,39.9300,1003.6,34,25.8,24.4,24.4,92,92,19.50,34,1.5
2026-07-25 23:20:30,116.2536,39.9239,850.0,1487,18.0,16.2,16.2,89,89,13.75,16,3.8
2026-07-26 00:02:22,116.4405,39.9345,500.0,5890,-4.9,-11.3,-11.3,61,61,2.11,255,11.6
"""


class WyomingParserTests(unittest.TestCase):
    def test_parse_profile_and_sort_levels(self) -> None:
        valid_at = datetime(2026, 7, 26, tzinfo=timezone.utc)
        profile = parse_wyoming_csv(
            raw_csv=SAMPLE_CSV,
            station_id="54511",
            valid_at=valid_at,
            source_url="https://example.test/sounding",
            fetched_at=valid_at,
            cache_status="miss",
        )

        self.assertEqual(profile.station_id, "54511")
        self.assertEqual(profile.level_count, 3)
        self.assertEqual(profile.surface_pressure_hpa, 1003.6)
        self.assertEqual(profile.top_pressure_hpa, 500.0)
        self.assertEqual(profile.levels[0].dewpoint_c, 24.4)
        self.assertEqual(profile.levels[-1].wind_speed_ms, 11.6)

    def test_station_id_validation(self) -> None:
        self.assertEqual(validate_station_id(" 54511 "), "54511")
        with self.assertRaises(ValueError):
            validate_station_id("ZBAA")

    def test_url_contains_station_and_cycle(self) -> None:
        valid_at = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
        url = build_wyoming_url("54511", valid_at, source="bufr")
        self.assertIn("id=54511", url)
        self.assertIn("2026-07-26+12%3A00%3A00", url)
        self.assertIn("src=BUFR", url)

    def test_cache_path_is_scoped_by_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = WyomingSoundingClient(Path(directory))
            csv_path, metadata_path = client._cache_paths(
                "54511",
                datetime(2026, 7, 26, tzinfo=timezone.utc),
            )

        self.assertTrue(str(csv_path).endswith("2026\\07\\26\\54511_00.csv"))
        self.assertTrue(str(metadata_path).endswith("54511_00.json"))

    def test_cached_profile_can_be_loaded_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = WyomingSoundingClient(Path(directory))
            valid_at = datetime(2026, 7, 26, tzinfo=timezone.utc)
            csv_path, metadata_path = client._cache_paths("54511", valid_at)
            csv_path.parent.mkdir(parents=True)
            csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
            metadata_path.write_text(
                json.dumps(
                    {
                        "source_url": "https://example.test/sounding",
                        "fetched_at": valid_at.isoformat(),
                    }
                ),
                encoding="utf-8",
            )

            profile = client.load_cached_profile(
                station_id="54511",
                sounding_date=date(2026, 7, 26),
                cycle="00",
            )

        self.assertEqual(profile.cache_status, "hit")
        self.assertEqual(profile.level_count, 3)


if __name__ == "__main__":
    unittest.main()
