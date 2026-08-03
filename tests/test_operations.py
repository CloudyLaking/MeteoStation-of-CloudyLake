import json

from meteostation.operations import RuntimeTraffic, _congestion_level, load_site_config


def test_congestion_indicator_levels() -> None:
    assert _congestion_level(0.2, 40.0, 60.0) == 3
    assert _congestion_level(0.8, 40.0, 60.0) == 2
    assert _congestion_level(0.2, 92.0, 60.0) == 1


def test_legacy_site_config_receives_new_defaults(tmp_path) -> None:
    path = tmp_path / "site.json"
    path.write_text(
        json.dumps(
            {
                "version": "V2.1.1",
                "theme": {
                    "primary": "#126E68",
                    "accent": "#F2C94C",
                    "blue": "#2563A9",
                },
                "homepage": {
                    "title": "中国天气自动分析",
                    "subtitle": "统一工作台",
                    "notice": "旧字段应被安全忽略",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = load_site_config(path)

    assert config.homepage.station_title == "探空工作台"
    assert config.footer.contact == "cloudylaking@outlook.com"


def test_monthly_traffic_counts_page_visits_only(tmp_path) -> None:
    traffic = RuntimeTraffic(tmp_path / "traffic.json")

    traffic.record("/", 200, 1200)
    traffic.record("/observations", 200, 800)
    traffic.record("/api/v1/site/stats", 200, 400)
    traffic.record("/static/site.js", 200, 300)
    snapshot = traffic.snapshot()

    assert snapshot["monthly_page_views"] == 2
    assert snapshot["requests"] == 4
    assert snapshot["month_key"]
