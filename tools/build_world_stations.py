# -*- coding: utf-8 -*-
"""Build config/world_stations.json from the NOAA IGRA2 global station list.

IGRA2 ids look like "ACM00078861": a 3-letter country code, "00", then the
5-digit WMO id. Only stations with reasonably recent soundings (last year
>= 2000) and a numeric WMO id are kept, which gives a stable directory for
OGIMET SYNOP lookups of major airports/cities worldwide.
"""
import json
import re
import urllib.request
from pathlib import Path

SOURCE = "https://www.ncei.noaa.gov/pub/data/igra/igra2-station-list.txt"
OUT = Path(__file__).resolve().parent.parent / "config" / "world_stations.json"


def parse_float(text: str) -> float:
    try:
        value = float(text)
        return value if value > -900 else 0.0
    except ValueError:
        return 0.0


def main() -> None:
    request = urllib.request.Request(SOURCE, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read().decode("utf-8", errors="replace")

    stations = []
    seen = set()
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 7:
            continue
        station_id = fields[0]
        if len(station_id) < 8:
            continue
        country = station_id[0:3]
        # IGRA2 ids are a 3-letter country code followed by an 8-character
        # station id; the WMO number is the final five digits.
        wmo = station_id[-5:]
        if not re.fullmatch(r"\d{5}", wmo):
            continue
        # Fields 1..3 are lat/lon/elevation; the station name is the run of
        # words before the first bare 4-digit year (start year), after which
        # come the end year and the number of observations.
        try:
            latitude = parse_float(fields[1])
            longitude = parse_float(fields[2])
            elevation = parse_float(fields[3])
        except IndexError:
            continue
        year_index = None
        for index in range(4, len(fields)):
            if re.fullmatch(r"\d{4}", fields[index]):
                year_index = index
                break
        if year_index is None or year_index + 2 > len(fields) - 1:
            continue
        name = " ".join(fields[4:year_index]).strip()
        try:
            last_year = int(fields[year_index + 1])
        except (IndexError, ValueError):
            continue
        if not name or last_year < 2000:
            continue
        if wmo in seen:
            continue
        seen.add(wmo)
        stations.append(
            {
                "wmo_id": wmo,
                "name": name,
                "country_code": country,
                "latitude": round(latitude, 4),
                "longitude": round(longitude, 4),
                "elevation_m": round(elevation, 1),
            }
        )

    stations.sort(key=lambda item: item["wmo_id"])
    OUT.write_text(
        json.dumps(stations, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"wrote {len(stations)} stations -> {OUT}")


if __name__ == "__main__":
    main()
