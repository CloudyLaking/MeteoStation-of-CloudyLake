import json

from meteostation.sounding.wis2_collector import (
    Wis2CollectorConfig,
    Wis2SoundingCollector,
)


def test_successful_download_clears_stale_disconnect_state(tmp_path) -> None:
    state_path = tmp_path / "wis2.json"
    collector = Wis2SoundingCollector(
        config=Wis2CollectorConfig(
            broker_host="example.test",
            topics=["cache/a/wis2/#"],
        ),
        archive_root=tmp_path / "archive",
        state_path=state_path,
    )

    collector._write_health(connected=False, message="Normal disconnection")
    collector._record_download(128)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["connected"] is True
    assert "message" not in state
    assert state["download_count"] == 1
    assert state["downloaded_bytes"] == 128
