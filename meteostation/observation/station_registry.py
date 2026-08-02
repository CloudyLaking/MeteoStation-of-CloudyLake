from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


STATION_REGIONS: dict[str, tuple[str, ...]] = {
    "华北": ("北京", "天津", "河北", "山西", "内蒙古"),
    "东北": ("辽宁", "吉林", "黑龙江"),
    "华东": ("上海", "江苏", "浙江", "安徽", "福建", "江西", "山东"),
    "华中": ("河南", "湖北", "湖南"),
    "华南": ("广东", "广西", "海南"),
    "西南": ("重庆", "四川", "贵州", "云南", "西藏"),
    "西北": ("陕西", "甘肃", "青海", "宁夏", "新疆"),
}


class StationLookupError(ValueError):
    pass


@dataclass(frozen=True)
class StationRecord:
    province: str
    wmo_id: str
    name: str
    latitude_code: str
    longitude_code: str
    pressure_sensor_elevation_m: float
    observation_elevation_m: float

    @property
    def display_name(self) -> str:
        return f"{self.province}{self.name}"

    @property
    def latitude(self) -> float:
        return _coordinate(self.latitude_code)

    @property
    def longitude(self) -> float:
        return _coordinate(self.longitude_code)

    def legacy_fields(self) -> list[str]:
        return [
            self.province,
            self.wmo_id,
            self.name,
            self.latitude_code,
            self.longitude_code,
            f"{self.pressure_sensor_elevation_m:g}",
            f"{self.observation_elevation_m:g}",
        ]

    def as_dict(self) -> dict[str, object]:
        return {
            "wmo_id": self.wmo_id,
            "name": self.name,
            "province": self.province,
            "display_name": self.display_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation_m": self.observation_elevation_m,
        }


@lru_cache(maxsize=1)
def station_records() -> tuple[StationRecord, ...]:
    path = (
        Path(__file__).resolve().parents[2]
        / "Basic_function"
        / "station info.txt"
    )
    records: list[StationRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        next(handle, None)
        for line in handle:
            fields = line.strip().split()
            if len(fields) < 7:
                continue
            try:
                records.append(
                    StationRecord(
                        province=fields[0],
                        wmo_id=fields[1],
                        name=fields[2],
                        latitude_code=fields[3],
                        longitude_code=fields[4],
                        pressure_sensor_elevation_m=float(fields[5]),
                        observation_elevation_m=float(fields[6]),
                    )
                )
            except ValueError:
                continue
    return tuple(records)


def search_stations(query: str, *, limit: int = 10) -> list[StationRecord]:
    normalized = query.strip().casefold()
    if not normalized:
        return []
    exact: list[StationRecord] = []
    partial: list[StationRecord] = []
    for record in station_records():
        keys = (
            record.wmo_id.casefold(),
            record.name.casefold(),
            record.display_name.casefold(),
        )
        if normalized in keys:
            exact.append(record)
        elif any(normalized in key for key in keys):
            partial.append(record)
    return (exact + partial)[:limit]


def stations_in_region(region: str) -> list[StationRecord]:
    provinces = STATION_REGIONS.get(region)
    if provinces is None:
        raise StationLookupError(f"未知地区：{region}")
    return [record for record in station_records() if record.province in provinces]


def resolve_station(query: str) -> StationRecord:
    normalized = query.strip().casefold()
    matches = search_stations(query, limit=20)
    exact = [
        record
        for record in matches
        if normalized
        in {
            record.wmo_id.casefold(),
            record.name.casefold(),
            record.display_name.casefold(),
        }
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        options = "、".join(
            f"{record.display_name} {record.wmo_id}"
            for record in exact[:6]
        )
        raise StationLookupError(f"站名不唯一，请输入站号：{options}")
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise StationLookupError(f"站表中找不到“{query}”")
    options = "、".join(
        f"{record.display_name} {record.wmo_id}"
        for record in matches[:6]
    )
    raise StationLookupError(f"请输入更完整的站名或站号：{options}")


def _coordinate(value: str) -> float:
    if len(value) < 3:
        return 0.0
    degree_digits = len(value) - 2
    return int(value[:degree_digits]) + int(value[degree_digits:]) / 60
