"""P0 acceptance: 100+ consecutive forecast queries during cache churn."""
import time
import urllib.request
import urllib.error
import json

BASE = "https://meteostation.top"
urls = [
    "/api/v1/forecast/surface/58362",
    "/api/v1/forecast/surface/54511",
    "/api/v1/forecast/surface/31.4,121.45",
    "/api/v1/forecast/sounding/58362?step=24",
    "/api/v1/forecast/sounding/54511?step=48",
    "/api/v1/forecast/surface/58362?model=aifs",
    "/api/v1/forecast/sounding/58362?model=aifs&step=24",
]

results = {"200": 0, "404": 0, "422": 0, "503": 0, "500": 0, "other": 0, "errors": []}
latencies = []
start = time.time()
for i in range(120):
    path = urls[i % len(urls)]
    t0 = time.time()
    try:
        with urllib.request.urlopen(BASE + path, timeout=60) as resp:
            body = resp.read()
            code = resp.status
            lat = (time.time() - t0) * 1000
            if code == 200:
                payload = json.loads(body)
                meta = payload.get("meta")
                if not meta or "data_age_hours" not in meta:
                    results["errors"].append(f"{path}: missing meta")
    except urllib.error.HTTPError as exc:
        code = exc.code
        lat = (time.time() - t0) * 1000
        detail = exc.read().decode("utf-8", "replace")[:200]
        results["errors"].append(f"{path}: HTTP {code} {detail}")
    except Exception as exc:  # network/parse
        code = "ERR"
        lat = (time.time() - t0) * 1000
        results["errors"].append(f"{path}: {type(exc).__name__} {exc}")
    key = str(code)
    results[key] = results.get(key, 0) + 1
    latencies.append(lat)

latencies.sort()
print(f"queries=120 elapsed={time.time()-start:.1f}s")
print(f"counts={ {k: v for k, v in results.items() if k != 'errors'} }")
print(f"p50={latencies[60]:.0f}ms p95={latencies[114]:.0f}ms max={latencies[-1]:.0f}ms")
if results["errors"]:
    print("errors:")
    for e in results["errors"][:10]:
        print(" ", e)
print("five_hundreds:", results["500"])
print("ACCEPT" if results["500"] == 0 and results.get("ERR", 0) == 0 and not results["errors"] else "REJECT")
