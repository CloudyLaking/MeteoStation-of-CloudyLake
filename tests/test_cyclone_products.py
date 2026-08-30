from meteostation.cyclone_products import cluster_tracks, haversine_km, match_system_identity, stable_system_id


def _track(lon):
    return [{"lat": 15.0, "lon": lon}, {"lat": 16.0, "lon": lon + 1}]


def test_track_distance_and_cluster_are_geographical():
    assert haversine_km(0, 0, 0, 1) > 100
    clusters = cluster_tracks([_track(130), _track(130.2), _track(150)], radius_km=350)
    assert sorted(item["member_count"] for item in clusters) == [1, 2]
    assert sorted(item["member_support_rate"] for item in clusters) == [1 / 3, 2 / 3]


def test_identity_match_requires_trajectory_evidence():
    candidate = {"system_id": stable_system_id("wpac", 2026, "2026-08-31T00:00:00+00:00", 15, 130), "points": _track(130)}
    result = match_system_identity({"points": _track(130.1)}, [candidate])
    assert result["match_basis"] == "trajectory-space-and-time"
    assert match_system_identity({"points": _track(170)}, [candidate]) is None
