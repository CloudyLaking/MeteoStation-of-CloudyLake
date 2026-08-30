"""Safe storage policy runner for the 50 GB production host.

Default is a dry-run.  ``--apply`` only removes explicitly regenerable
temporary files and stale cache entries; raw observations and model source
archives are never selected by this script.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


def candidates(project_root: Path, now: float | None = None) -> list[Path]:
    now = now or time.time()
    selected: list[Path] = []
    safe_roots = [project_root / "data" / "cache", project_root / "data" / "tmp"]
    for root in safe_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and now - path.stat().st_mtime > 7 * 86400:
                selected.append(path)
    for path in project_root.rglob("*.part"):
        if "data/raw" not in path.as_posix() and now - path.stat().st_mtime > 2 * 86400:
            selected.append(path)
    return sorted(set(selected))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="explicitly request the default non-destructive mode")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    items = candidates(args.root)
    payload = {"dry_run": not args.apply, "candidate_count": len(items), "candidates": [str(item) for item in items]}
    if args.apply:
        removed = []
        for item in items:
            try:
                item.unlink()
                removed.append(str(item))
            except OSError:
                continue
        payload["removed"] = removed
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
