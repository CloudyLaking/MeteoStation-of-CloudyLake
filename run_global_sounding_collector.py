"""Backfill and retain three days of globally active Wyoming soundings."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from meteostation.sounding.global_collector import run_global_collector


PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "global_sounding_collector.json",
    )
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    try:
        asyncio.run(
            run_global_collector(
                config_path=arguments.config,
                project_root=PROJECT_ROOT,
                once=arguments.once,
            )
        )
    except KeyboardInterrupt:
        print("全球探空回填采集器已停止。")
