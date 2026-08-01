"""Subscribe to global WIS2 TEMP notifications and retain raw BUFR for 3 days."""

from __future__ import annotations

import argparse
from pathlib import Path

from meteostation.sounding.wis2_collector import (
    Wis2SoundingCollector,
    load_wis2_config,
)


PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "wis2_sounding_collector.json",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    collector = Wis2SoundingCollector(
        config=load_wis2_config(arguments.config),
        archive_root=PROJECT_ROOT / "data" / "raw" / "wis2_soundings",
        state_path=PROJECT_ROOT / "data" / "state" / "wis2_sounding_collector.json",
    )
    try:
        collector.run_forever()
    except KeyboardInterrupt:
        print("WIS2 全球探空实时采集器已停止。")
