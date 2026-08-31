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
    traffic.record("/error.php", 404, 100)
    snapshot = traffic.snapshot()

    # Raw requests count everything; page views come only from
    # record_page_view (successful real page routes, deduplicated).
    assert snapshot["monthly_page_views"] == 0
    assert snapshot["requests"] == 5
    assert snapshot["path_counts"]["page"] == 2
    assert snapshot["path_counts"]["other"] == 1
    assert snapshot["month_key"]

    traffic.record_page_view("s1", "/")
    traffic.record_page_view("s1", "/")
    traffic.record_page_view("s1", "/observations")
    traffic.record_page_view("s2", "/")
    assert traffic.snapshot()["monthly_page_views"] == 3

    traffic.record_unique_visitor("203.0.113.8")
    traffic.record_unique_visitor("203.0.113.8")
    traffic.record_unique_visitor("198.51.100.4")
    unique_snapshot = traffic.snapshot()
    assert unique_snapshot["monthly_unique_visitors"] == 2
    assert all(
        address not in json.dumps(unique_snapshot)
        for address in ("203.0.113.8", "198.51.100.4")
    )
