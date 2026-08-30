import os
import time

from scripts.storage_maintenance import candidates


def test_storage_dry_run_selects_only_regenerable_files(tmp_path):
    cache = tmp_path / "data" / "cache"
    raw = tmp_path / "data" / "raw"
    cache.mkdir(parents=True)
    raw.mkdir(parents=True)
    old_cache = cache / "old.json"
    old_raw = raw / "old.bufr"
    old_cache.write_text("{}", encoding="utf-8")
    old_raw.write_bytes(b"raw")
    old = time.time() - 8 * 86400
    os.utime(old_cache, (old, old))
    os.utime(old_raw, (old, old))
    assert candidates(tmp_path) == [old_cache]
