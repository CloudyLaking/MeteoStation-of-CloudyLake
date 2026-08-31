from __future__ import annotations

import base64
import json
from datetime import date
from pathlib import Path

from meteostation.sounding.wis2_profile import Wis2SoundingArchive


SAMPLE_BUFR = (
    "QlVGUgAAxAQAABYAAAAAAAAAAgRuHgAH6ggfAAAAAAAJAAABgMk0AACZAFaT"
    "////////////kyiPk/VD4AAE6OrbEhT6M3L////////////////AAX//oAAB"
    "XhNEv///////+nhaI/loF3//oAAA+hVAP///////+oxaMbjcHb//oAAAlhhgP"
    "///////+q/6S/mkHv//oAAAZBr0P///////+ri6UZjIBr//oAAAMh9vv////"
    "///+tEaYJnMF0AANzc3Nw=="
)


def test_wis2_archive_decodes_real_temp_bufr(tmp_path: Path) -> None:
    directory = tmp_path / "2026" / "08" / "31"
    directory.mkdir(parents=True)
    (directory / "part.bufr4").write_bytes(base64.b64decode(SAMPLE_BUFR))
    (directory / "index.json").write_text(
        json.dumps(
            {
                "items": {
                    "43295|2026-08-31T00:00:00+00:00": [
                        {
                            "data_file": "part.bufr4",
                            "source_url": "https://example.test/part.bufr4",
                            "downloaded_at": "2026-08-31T00:10:00+00:00",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    profile = Wis2SoundingArchive(tmp_path).load_profile(
        "43295",
        date(2026, 8, 31),
        "00",
    )

    assert profile.source == "WMO WIS 2.0 TEMP"
    assert profile.level_count == 5
    assert profile.surface_pressure_hpa == 70
    assert profile.top_pressure_hpa == 10
    assert profile.station_latitude is not None
    assert profile.station_longitude is not None

