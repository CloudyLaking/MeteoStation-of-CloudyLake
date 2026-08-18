#!/bin/bash
# P0 deployment verification (run on the production host, read-only except pytest cache).
set -e
cd /opt/meteostation
echo "=== imports ==="
.venv/bin/python -c 'from meteostation.forecast import manifest, collector; from web import app; print("imports ok")'
echo "=== new tests ==="
.venv/bin/python -m pytest tests/test_forecast_manifest.py tests/test_forecast_api.py -q --no-header -p no:warnings
echo "=== collector config ==="
.venv/bin/python -c 'import json; c=json.load(open("config/forecast_collector.json")); print("retain", c["retain_complete_cycles"], "max_stale", c["max_stale_hours"])'
echo "=== bootstrap manifest (once) ==="
.venv/bin/python run_forecast_collector.py --once > /tmp/forecast_once.json
.venv/bin/python -c 'import json; d=json.load(open("/tmp/forecast_once.json")); print("bootstrap:", json.dumps(d.get("bootstrap"), ensure_ascii=False)); print("removed:", json.dumps(d.get("removed_cycles"), ensure_ascii=False))'
echo "=== manifest ==="
.venv/bin/python -c 'import json,os; p="data/state/manifest/current.json"; print(json.dumps(json.load(open(p)) if os.path.exists(p) else {}, ensure_ascii=False, indent=1)[:1200])'
