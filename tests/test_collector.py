import asyncio
import json
import unittest
from datetime import datetime, timezone
import tempfile
from pathlib import Path
from types import SimpleNamespace

from meteostation.sounding.collector import (
    CollectorConfig,
    SoundingCollector,
    collector_item_key,
    prepare_product_store,
    product_exists,
    recent_cycles,
)


class CollectorScheduleTests(unittest.TestCase):
    def test_static_products_are_disabled_by_default(self) -> None:
        config = CollectorConfig(
            stations=[
                {
                    "wmo_id": "58362",
                    "name": "上海宝山",
                    "name_en": "Baoshan, Shanghai",
                }
            ]
        )

        self.assertFalse(config.generate_static_products)

    def test_recent_cycles_are_newest_first(self) -> None:
        cycles = recent_cycles(
            reference_time=datetime(2026, 7, 26, 6, tzinfo=timezone.utc),
            cycles=["00", "12"],
            lookback_hours=24,
        )

        self.assertEqual(
            cycles,
            [
                datetime(2026, 7, 26, 0, tzinfo=timezone.utc),
                datetime(2026, 7, 25, 12, tzinfo=timezone.utc),
            ],
        )

    def test_future_cycle_is_not_scheduled(self) -> None:
        cycles = recent_cycles(
            reference_time=datetime(2026, 7, 26, 6, tzinfo=timezone.utc),
            cycles=["12"],
            lookback_hours=24,
        )

        self.assertNotIn(
            datetime(2026, 7, 26, 12, tzinfo=timezone.utc),
            cycles,
        )

    def test_unattempted_history_precedes_latest_cycle_retry(self) -> None:
        reference_time = datetime(2026, 7, 27, 13, tzinfo=timezone.utc)
        latest = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)
        calls: list[tuple[str, str]] = []

        class FakeClient:
            async def get_profile(
                self,
                station_id,
                sounding_date,
                cycle,
                source,
            ):
                calls.append((sounding_date.isoformat(), cycle))
                return SimpleNamespace(cache_status="hit")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "items": {
                            collector_item_key("58362", latest): {
                                "status": "waiting",
                                "attempts": 1,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            collector = SoundingCollector(
                config=CollectorConfig(
                    lookback_hours=24,
                    request_spacing_seconds=0,
                    cycles=["00", "12"],
                    stations=[
                        {
                            "wmo_id": "58362",
                            "name": "上海宝山",
                            "name_en": "Baoshan, Shanghai",
                        }
                    ],
                ),
                raw_data_root=root / "raw",
                product_root=root / "products",
                state_path=state_path,
            )
            collector.client = FakeClient()

            asyncio.run(collector.run_once(reference_time=reference_time))

        self.assertEqual(
            calls,
            [
                ("2026-07-27", "00"),
                ("2026-07-27", "12"),
            ],
        )

    def test_product_is_complete_only_when_both_diagrams_exist(self) -> None:
        valid_at = datetime(2026, 7, 26, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product_directory = root / "soundings" / "2026" / "07" / "26"
            product_directory.mkdir(parents=True)
            for diagram in ("skewt", "stuve"):
                (product_directory / f"54511_00_{diagram}.png").touch()
                (product_directory / f"54511_00_{diagram}.json").touch()

            self.assertTrue(product_exists(root, "54511", valid_at))
            (product_directory / "54511_00_stuve.png").unlink()
            self.assertFalse(product_exists(root, "54511", valid_at))

    def test_renderer_upgrade_clears_products_but_not_raw_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product_root = root / "products"
            sounding_root = product_root / "soundings"
            sounding_root.mkdir(parents=True)
            (sounding_root / ".renderer-version").write_text(
                "old-renderer\n",
                encoding="utf-8",
            )
            (sounding_root / "old.png").touch()
            raw_file = root / "raw" / "wyoming" / "profile.csv"
            raw_file.parent.mkdir(parents=True)
            raw_file.write_text("archived observation", encoding="utf-8")

            cleared = prepare_product_store(
                product_root,
                renderer_version="new-renderer",
            )

            self.assertTrue(cleared)
            self.assertFalse((sounding_root / "old.png").exists())
            self.assertEqual(
                (sounding_root / ".renderer-version").read_text(
                    encoding="utf-8"
                ),
                "new-renderer\n",
            )
            self.assertTrue(raw_file.exists())

    def test_matching_renderer_version_keeps_products(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            product_root = Path(directory)
            sounding_root = product_root / "soundings"
            sounding_root.mkdir()
            (sounding_root / ".renderer-version").write_text(
                "current\n",
                encoding="utf-8",
            )
            product = sounding_root / "keep.png"
            product.touch()

            cleared = prepare_product_store(
                product_root,
                renderer_version="current",
            )

            self.assertFalse(cleared)
            self.assertTrue(product.exists())


if __name__ == "__main__":
    unittest.main()
