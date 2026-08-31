"""Stream NOAA IBTrACS WP CSV into a small gzip JSON index, then discard CSV bytes."""

from __future__ import annotations

import csv
import gzip
import io
import json
from collections import defaultdict
from pathlib import Path

import requests


URL = "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.WP.list.v04r01.csv"
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "products" / "cyclones" / "ibtracs-wp.json.gz"


def number(value: str) -> float | None:
    try: return float(value)
    except (TypeError, ValueError): return None


def build() -> dict[str, object]:
    storms: dict[str, dict[str, object]] = {}
    with requests.get(URL, stream=True, timeout=90) as response:
        response.raise_for_status()
        response.raw.decode_content = True
        reader = csv.DictReader(io.TextIOWrapper(response.raw, encoding="utf-8", newline=""))
        for row in reader:
            sid, iso_time = row.get("SID", ""), row.get("ISO_TIME", "")
            if not sid or not iso_time or not row.get("SEASON", "").isdigit() or int(row["SEASON"]) < 1950:
                continue
            lat, lon = number(row.get("LAT", "")), number(row.get("LON", ""))
            if lat is None or lon is None: continue
            # Six-hour points protect size while preserving synoptic tracks.
            if iso_time[11:13] not in {"00", "06", "12", "18"}: continue
            wind = number(row.get("WMO_WIND", "")) or number(row.get("USA_WIND", ""))
            pressure = number(row.get("WMO_PRES", "")) or number(row.get("USA_PRES", ""))
            storm = storms.setdefault(sid, {"sid": sid, "season": int(row["SEASON"]), "basin": row.get("BASIN") or "WP", "name": row.get("NAME") or "UNNAMED", "points": [], "max_wind_kt": None})
            storm["points"].append({"time": iso_time, "lat": lat, "lon": lon, "wind_kt": wind, "pressure_hpa": pressure})
            if wind is not None: storm["max_wind_kt"] = max(float(storm.get("max_wind_kt") or 0), wind)
    output = []
    for storm in storms.values():
        points = storm["points"]
        if len(points) < 3: continue
        storm["start_time"], storm["end_time"] = points[0]["time"], points[-1]["time"]
        output.append(storm)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUTPUT, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump({"source": URL, "subset": "Western Pacific, 1950-present, six-hourly", "storms": output}, handle, ensure_ascii=False, separators=(",", ":"))
    return {"output": str(OUTPUT), "storms": len(output), "bytes": OUTPUT.stat().st_size}


if __name__ == "__main__": print(json.dumps(build(), ensure_ascii=False))
