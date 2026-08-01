import unittest
from datetime import datetime, timedelta, timezone

from meteostation.observation import (
    parse_ogimet_csv,
    parse_qweather_hourly_html,
    parse_qweather_realtime,
    to_legacy_weather_table,
)
from meteostation.observation.station_registry import resolve_station


SAMPLE_CSV = """WMO_ID,ANO,MES,DIA,HORA,MINUTO,PARTE
58362,2026,07,26,00,00,AAXX 26001 58362 14/78 /1604 10307 20251 30073 40083 52005 60001 333 10358 20287 3/027 59012 70000 90761 91109==
58362,2026,07,26,03,00,AAXX 26031 58362 14/80 /1904 10338 20241 30076 40085 52003 60001 333 10358 20287 3/027 59008 70000 90761 91111==
"""


class ObservationParserTests(unittest.TestCase):
    def test_qweather_hourly_table_selects_exact_hour(self) -> None:
        html = """
        <table class="border">
          <tr><th>时次</th><th>瞬时温度</th><th>地面气压</th><th>相对湿度</th>
          <th>瞬时风向</th><th>瞬时风速</th><th>1小时降水</th><th>10分钟平均能见度</th></tr>
          <tr><td>2026-07-26 08:00 +0800</td><td>30.2</td><td>1008.0</td><td>74</td>
          <td>180/S</td><td>3.5</td><td>0.0</td><td>30.0</td></tr>
        </table>
        """
        target = datetime(
            2026,
            7,
            26,
            8,
            tzinfo=timezone(timedelta(hours=8)),
        )
        observation = parse_qweather_hourly_html(
            html,
            station_id="58362",
            source_url="https://example.test/hourly/",
            target=target,
        )

        self.assertEqual(observation.temperature_c, 30.2)
        self.assertEqual(observation.station_pressure_hpa, 1008.0)
        self.assertEqual(observation.relative_humidity_pct, 74)
        self.assertEqual(observation.wind_direction_deg, 180)

    def test_station_can_be_resolved_by_number_or_chinese_name(self) -> None:
        self.assertEqual(resolve_station("58362").wmo_id, "58362")
        self.assertEqual(resolve_station("\u5b9d\u5c71").wmo_id, "58362")

    def test_synop_groups_are_decoded(self) -> None:
        observations = parse_ogimet_csv(SAMPLE_CSV, station_id="58362")

        self.assertEqual(len(observations), 2)
        first = observations[0]
        self.assertEqual(first.temperature_c, 30.7)
        self.assertEqual(first.dewpoint_c, 25.1)
        self.assertEqual(first.station_pressure_hpa, 1007.3)
        self.assertEqual(first.wind_direction_deg, 160)
        self.assertEqual(first.wind_speed_ms, 4)
        self.assertEqual(first.gust_speed_ms, 9)
        self.assertEqual(first.precipitation_1h_mm, 0)
        self.assertIsNotNone(first.relative_humidity_pct)

    def test_legacy_table_is_newest_first(self) -> None:
        observations = parse_ogimet_csv(SAMPLE_CSV, station_id="58362")
        from meteostation.observation.models import SurfaceObservationSeries

        series = SurfaceObservationSeries(
            station_id="58362",
            station_name="上海宝山",
            station_name_en="Baoshan",
            latitude=31.39,
            longitude=121.45,
            elevation_m=3.3,
            observation_date=observations[0].observed_at.date(),
            source="OGIMET SYNOP",
            source_url="https://example.test",
            fetched_at=observations[-1].observed_at,
            cache_status="not-stored",
            observations=observations,
        )
        table = to_legacy_weather_table(series)

        self.assertEqual(table[0][0], "时次")
        self.assertTrue(table[1][0].startswith("2026-07-26 03:00"))
        self.assertEqual(table[1][4], "190/S")

    def test_qweather_realtime_json_is_normalized(self) -> None:
        realtime = parse_qweather_realtime(
            {
                "wmo": "58367",
                "realtime": {
                    "T": 34.3,
                    "RH": 56,
                    "P": 1005.5,
                    "WD2m": 270,
                    "WS2m": 0.28,
                    "R1h": 0.0,
                    "V10m": 27.486,
                    "time": {"T": "2026-07-26T08:25:00"},
                },
            },
            station_id="58367",
            source_url="https://example.test/realtime/",
        )

        self.assertEqual(realtime.temperature_c, 34.3)
        self.assertEqual(realtime.wind_direction_deg, 270)
        self.assertEqual(realtime.visibility_km, 27.486)


if __name__ == "__main__":
    unittest.main()
