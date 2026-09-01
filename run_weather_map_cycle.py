"""Generate the latest available 00/12 UTC China weather-map cycle."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
STATE_PATH = PROJECT_ROOT / "data" / "state" / "weather_map_collector.json"
RETENTION_DAYS = 3


def latest_valid_cycle(now: datetime) -> tuple[datetime, str]:
    utc_now = now.astimezone(timezone.utc)
    cycle_hour = 12 if utc_now.hour >= 12 else 0
    valid_at = utc_now.replace(
        hour=cycle_hour,
        minute=0,
        second=0,
        microsecond=0,
    )
    return valid_at, f"{cycle_hour:02d}"


def write_state(payload: dict[str, object]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, STATE_PATH)


def cleanup_old_products(now: datetime) -> None:
    cutoff = now.astimezone(timezone.utc).date() - timedelta(days=RETENTION_DAYS)
    roots = [
        PROJECT_ROOT / "data" / "previews" / "weather_maps",
        PROJECT_ROOT / "data" / "raw" / "ecmwf",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for year_directory in root.iterdir():
            if not year_directory.is_dir() or not year_directory.name.isdigit():
                continue
            for month_directory in year_directory.iterdir():
                if not month_directory.is_dir() or not month_directory.name.isdigit():
                    continue
                for day_directory in month_directory.iterdir():
                    try:
                        archive_date = datetime.strptime(
                            f"{year_directory.name}-{month_directory.name}-{day_directory.name}",
                            "%Y-%m-%d",
                        ).date()
                    except (ValueError, OSError):
                        continue
                    if day_directory.is_dir() and archive_date < cutoff:
                        import shutil

                        shutil.rmtree(day_directory)


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    started_at = datetime.now(timezone.utc)
    valid_at, cycle = latest_valid_cycle(started_at)
    command = [
        sys.executable,
        str(PROJECT_ROOT / "run_weather_map.py"),
        "--date",
        valid_at.date().isoformat(),
        "--cycle",
        cycle,
        "--download",
        "--download-climatology",
        "--include-cyclone-tracks",
        "--render-preview",
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=45 * 60,
        check=False,
    )
    checked_at = datetime.now(timezone.utc)
    payload = {
        "checked_at": checked_at.isoformat(),
        "valid_at": valid_at.isoformat(),
        "cycle": cycle,
        "status": "complete" if completed.returncode == 0 else "failed",
        "return_code": completed.returncode,
        "stdout_tail": completed.stdout[-3000:],
        "stderr_tail": completed.stderr[-3000:],
    }
    write_state(payload)
    if completed.returncode == 0:
        cleanup_old_products(checked_at)
    else:
        print(completed.stderr, file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
