from datetime import datetime, timezone

import numpy as np

from meteostation.ensemble import cluster_scenarios, load_snapshot, summarize_members, threshold_support


def test_ensemble_statistics_keep_missing_values_as_null():
    result = summarize_members([[1.0, 2.0], [3.0, np.nan]])
    assert result["valid_members"] == [2, 1]
    assert result["median"] == [2.0, 2.0]
    assert result["p90"][1] == 2.0
    assert threshold_support([[1.0, 3.0], [2.0, np.nan]], 2.0) == [0.5, 1.0]


def test_cluster_scenarios_reports_real_member_indexes_and_medoid():
    clusters = cluster_scenarios([[0, 0], [0.2, 0.1], [10, 10], [10.1, 9.9]], k=2)
    assert sum(item["member_count"] for item in clusters) == 4
    assert all("medoid_member_index" in item for item in clusters)


def test_snapshot_rejects_interpolated_steps(tmp_path):
    path = tmp_path / "latest.json"
    path.write_text('{"model":"aifs-ens","initialized_at":"2026-08-31T00:00:00+00:00","steps":[0,3],"members":51,"variables":["2t"]}', encoding="utf-8")
    try:
        load_snapshot(path)
    except ValueError as exc:
        assert "native" in str(exc)
    else:
        raise AssertionError("non-native steps must be rejected")
