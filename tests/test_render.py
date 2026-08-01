import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from meteostation.sounding.render import (
    render_skewt_quicklook,
    render_stuve_quicklook,
)
from meteostation.sounding.wyoming import parse_wyoming_csv
from tests.test_wyoming import SAMPLE_CSV


class SoundingRenderTests(unittest.TestCase):
    def test_both_english_diagram_products_are_created(self) -> None:
        valid_at = datetime(2026, 7, 26, tzinfo=timezone.utc)
        profile = parse_wyoming_csv(
            raw_csv=SAMPLE_CSV,
            station_id="54511",
            valid_at=valid_at,
            source_url="https://example.test/sounding",
            fetched_at=valid_at,
            cache_status="hit",
        )

        with tempfile.TemporaryDirectory() as directory:
            product_root = Path(directory)
            skewt = render_skewt_quicklook(
                profile,
                product_root=product_root,
                station_name="Beijing",
            )
            stuve = render_stuve_quicklook(
                profile,
                product_root=product_root,
                station_name="Beijing",
            )

            self.assertTrue((product_root / skewt.image_path).exists())
            self.assertTrue((product_root / stuve.image_path).exists())
            self.assertEqual(skewt.diagram_type, "skewt")
            self.assertEqual(stuve.diagram_type, "stuve")
            self.assertEqual(skewt.station_name, "Beijing")


if __name__ == "__main__":
    unittest.main()
