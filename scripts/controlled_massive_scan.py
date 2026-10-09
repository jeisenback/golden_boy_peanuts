#!/usr/bin/env python3
"""Controlled scan: monthly `as_of` snapshots for target symbols against Massive
- Uses POLYGON_API_KEY from environment (stored in .env locally)
- Paces requests and backs off on 429
- Saves JSON per-symbol/per-asof into docs/vendor_evaluation/samples/controlled_scan
"""
import os
import time
import json
import requests
from datetime import datetime, timedelta

KEY = os.environ.get("POLYGON_API_KEY")
BASE = "https://api.massive.com/v3/reference/options/contracts"
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "vendor_evaluation", "samples", "controlled_scan")
os.makedirs(OUT_DIR, exist_ok=True)

symbols = ["USO", "XOM", "CVX", "XLE", "CL", "BZ"]
# 12 monthly snapshots ending 2022-01-19 (inclusive)
end = datetime(2022, 1, 19)
as_of_dates = []
for i in range(11, -1, -1):
    dt = end - timedelta(days=30 * i)  # approx monthly spacing
    as_of_dates.append(dt.strftime("%Y-%m-%d"))

# request pacing and retry config
SLEEP_BETWEEN = 5  # seconds between requests
MAX_RETRIES = 4
BACKOFF_FACTOR = 2

session = requests.Session()

for s in symbols:
    for as_of in as_of_dates:
        params = {"underlying_ticker": s, "as_of": as_of, "limit": 100, "order": "asc", "sort": "ticker"}
        if KEY:
            params["apiKey"] = KEY
        attempt = 0
        while True:
            attempt += 1
            try:
                r = session.get(BASE, params=params, timeout=30)
            except Exception as e:
                out = {"error": str(e)}
                fname = os.path.join(OUT_DIR, f"{s}_asof_{as_of}_err.json")
                with open(fname, "w", encoding="utf-8") as f:
                    json.dump(out, f, indent=2)
                print(f"{s} {as_of} -> ERROR saved {fname}")
                break

            if r.status_code == 200:
                try:
                    j = r.json()
                except Exception:
                    j = {"text": r.text}
                out = {"url": r.url, "status_code": r.status_code, "json": j}
                fname = os.path.join(OUT_DIR, f"{s}_asof_{as_of}.json")
                with open(fname, "w", encoding="utf-8") as f:
                    json.dump(out, f, indent=2)
                print(f"{s} {as_of} -> 200 saved {fname}")
                time.sleep(SLEEP_BETWEEN)
                break
            elif r.status_code == 429:
                if attempt > MAX_RETRIES:
                    out = {"url": r.url, "status_code": r.status_code, "json": r.json()}
                    fname = os.path.join(OUT_DIR, f"{s}_asof_{as_of}_429.json")
                    with open(fname, "w", encoding="utf-8") as f:
                        json.dump(out, f, indent=2)
                    print(f"{s} {as_of} -> 429 saved {fname} (max retries reached)")
                    break
                wait = (BACKOFF_FACTOR ** (attempt - 1)) * SLEEP_BETWEEN
                print(f"{s} {as_of} -> 429; backing off {wait}s (attempt {attempt})")
                time.sleep(wait)
                continue
            else:
                # save other status codes
                try:
                    j = r.json()
                except Exception:
                    j = {"text": r.text}
                out = {"url": r.url, "status_code": r.status_code, "json": j}
                fname = os.path.join(OUT_DIR, f"{s}_asof_{as_of}_status_{r.status_code}.json")
                with open(fname, "w", encoding="utf-8") as f:
                    json.dump(out, f, indent=2)
                print(f"{s} {as_of} -> {r.status_code} saved {fname}")
                time.sleep(SLEEP_BETWEEN)
                break

print("Controlled scan complete.")
