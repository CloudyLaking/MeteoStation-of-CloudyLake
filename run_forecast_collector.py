"""Run the ECMWF IFS/AIFS forecast-cycle monitor."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from meteostation.forecast.collector import (
    ForecastCollector,
    load_forecast_collector_config,
)


PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor and cache ECMWF IFS/AIFS Open Data cycles."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "forecast_collector.json",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one monitoring pass and exit.",
    )
    return parser.parse_args()


async def run() -> None:
    args = parse_args()
    config = load_forecast_collector_config(args.config)
    collector = ForecastCollector(
        config=config,
        cache_root=PROJECT_ROOT / "data" / "raw",
        state_path=PROJECT_ROOT / "data" / "state" / "forecast_collector.json",
    )
    if args.once:
        print(
            json.dumps(
                await collector.run_once(),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(
        "ECMWF forecast monitor started; "
        f"checking every {config.poll_interval_seconds} seconds.",
        flush=True,
    )
    await collector.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("ECMWF forecast monitor stopped.")
