#!/usr/bin/env python3
import os
import json
import time
import requests

KEY = os.environ.get("POLYGON_API_KEY")
BASE = "https://api.massive.com/v3/reference/options/contracts"
SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "vendor_evaluation", "samples")
os.makedirs(SAMPLES_DIR, exist_ok=True)

symbols = ["USO", "XOM", "CVX", "XLE", "CL=F", "BZ=F"]
date_as_of = "2022-01-19"

params_common = {"limit": 100, "order": "asc", "sort": "ticker", "as_of": date_as_of}

for s in symbols:
    params = dict(params_common)
    params["underlying_ticker"] = s
    if KEY:
        params["apiKey"] = KEY
    try:
        resp = requests.get(BASE, params=params, timeout=30)
        out = {
            "url": resp.url,
            "status_code": resp.status_code,
            "headers": {k: v for k, v in resp.headers.items() if k.lower() in ("content-type", "x-rate-limit-limit", "x-rate-limit-remaining")},
        }
        try:
            out["json"] = resp.json()
        except Exception:
            out["text"] = resp.text[:10000]
    except Exception as e:
        out = {"error": str(e)}

    fname = os.path.join(SAMPLES_DIR, f"massive_contracts_{s.replace('=','_')}_asof_{date_as_of}.json")
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"Saved as-of sample for {s} -> {fname}")
    time.sleep(1)

print("Done.")
