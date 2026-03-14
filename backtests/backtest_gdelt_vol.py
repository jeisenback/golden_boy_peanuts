#!/usr/bin/env python3
"""Prototype backtest: GDELT volume spikes -> realized volatility proxy.

Usage:
  python backtest_gdelt_vol.py --gdelt sample_gdelt.csv --prices sample_prices.csv --threshold 2.0 --hold 3
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import numpy as np
import pandas as pd
from typing import Any, Dict


def load_gdelt(path: pathlib.Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.sort_values("date").set_index("date")
    return df


def load_prices(path: pathlib.Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    df = df.sort_values("date").set_index("date")
    df["ret"] = df["close"].pct_change()
    return df


def detect_events(gdelt: pd.DataFrame, window: int = 14, threshold: float = 2.0) -> pd.Series:
    # use rolling z-score on `articles` count
    s = gdelt["articles"].astype(float)
    mu = s.rolling(window=window, min_periods=5).mean()
    sigma = s.rolling(window=window, min_periods=5).std().replace(0, np.nan)
    z = (s - mu) / sigma
    return z.fillna(0) > threshold


def realized_abs_return_series(prices: pd.DataFrame, hold: int) -> pd.Series:
    # realized absolute return over next `hold` business days
    abs_ret = prices["ret"].abs()
    # rolling forward mean of absolute returns
    return abs_ret.rolling(window=hold, min_periods=1).sum().shift(-hold + 1)


def evaluate(gdelt_path: pathlib.Path, prices_path: pathlib.Path, threshold: float, hold: int) -> Dict[str, Any]:
    gd = load_gdelt(gdelt_path)
    pr = load_prices(prices_path)

    events = detect_events(gd, window=14, threshold=threshold)

    rv = realized_abs_return_series(pr, hold=hold)

    # align on dates
    df = pd.DataFrame({"articles": gd["articles"], "event": events}).join(pr["close"], how="inner")
    df = df.join(rv.rename("realized_abs_return"), how="left")

    # drop na realized
    df = df.dropna(subset=["realized_abs_return"]) 

    event_rows = df[df["event"]]
    non_event_rows = df[~df["event"]]

    def stats(s):
        return {"count": int(s.count()), "mean": float(s.mean()), "median": float(s.median()), "std": float(s.std())}

    out = {
        "threshold": threshold,
        "hold_days": hold,
        "events": stats(event_rows["realized_abs_return"]),
        "non_events": stats(non_event_rows["realized_abs_return"]),
    }

    return out


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(description="Backtest prototype: GDELT volume -> realized volatility")
    p.add_argument("--gdelt", required=True)
    p.add_argument("--prices", required=True)
    p.add_argument("--threshold", type=float, default=2.0)
    p.add_argument("--hold", type=int, default=3)
    args = p.parse_args(argv)

    out = evaluate(pathlib.Path(args.gdelt), pathlib.Path(args.prices), threshold=args.threshold, hold=args.hold)
    import json

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
