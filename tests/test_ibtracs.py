from __future__ import annotations

import gzip
import json
from pathlib import Path

from meteostation.ibtracs import analogs, load_index, search_storms


def write_index(path: Path) -> None:
    storms = [
        {
            "sid": "A",
            "name": "TARGET",
            "season": 2025,
            "basin": "WP",
            "start_time": "2025-08-01 00:00:00",
            "end_time": "2025-08-03 00:00:00",
            "max_wind_kt": 80,
            "points": [
                {"lat": 10, "lon": 130},
                {"lat": 12, "lon": 128},
                {"lat": 14, "lon": 126},
            ],
        },
        {
            "sid": "B",
            "name": "ANALOG",
            "season": 2015,
            "basin": "WP",
            "start_time": "2015-08-02 00:00:00",
            "end_time": "2015-08-04 00:00:00",
            "max_wind_kt": 75,
            "points": [
                {"lat": 10.2, "lon": 130.1},
                {"lat": 12.2, "lon": 128.1},
                {"lat": 14.2, "lon": 126.1},
            ],
        },
    ]
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump({"storms": storms}, handle)


def test_ibtracs_search_and_analog_ranking(tmp_path: Path) -> None:
    path = tmp_path / "ibtracs.json.gz"
    write_index(path)
    load_index.cache_clear()

    matches = search_storms(path, "target")
    result = analogs(path, "A")

    assert matches[0]["sid"] == "A"
    assert result is not None
    assert result["analogs"][0]["sid"] == "B"
    assert result["analogs"][0]["score"] > 0.9
    assert result["analogs"][0]["era5_link"].startswith("/reanalysis?date=")
    assert result["era5_environment"] == "可从案例日期打开 ERA5；环境场加入评分前保持为空。"

