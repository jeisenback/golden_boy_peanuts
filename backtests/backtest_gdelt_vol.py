#!/usr/bin/env python3
"""Minimal, well-formed backtest helper used by tests.

This smaller implementation keeps behavior needed by the unit test and
avoids prior merge-marker issues.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

import pandas as pd


def _stats(s: pd.Series) -> dict[str, Any]:
    return {
        "count": int(s.count()),
        "mean": float(s.mean() if s.count() else 0.0),
        "median": float(s.median() if s.count() else 0.0),
        "std": float(s.std() if s.count() > 1 else 0.0),
    }


def evaluate(gdelt_path: pathlib.Path, prices_path: pathlib.Path, threshold: float, hold: int) -> dict[str, Any]:
    gd = pd.read_csv(gdelt_path, parse_dates=["date"]).rename(columns=str.lower).set_index("date")
    pr = pd.read_csv(prices_path, parse_dates=["date"]).rename(columns=str.lower).set_index("date")
    pr["ret"] = pr["close"].pct_change()

    # Very small heuristic: consider rows where articles > threshold * mean as events
    mean_articles = float(gd["articles"].mean())
    events = gd["articles"] > (threshold * mean_articles)

    union_idx = gd.index.union(pr.index).sort_values()
    prr = pr.reindex(union_idx).ffill()
    rv = prr["ret"].abs().rolling(window=hold, min_periods=1).sum().shift(-hold + 1)

    df = pd.DataFrame({"articles": gd["articles"].reindex(union_idx), "event": events.reindex(union_idx).fillna(False)})
    df = df.join(rv.rename("realized_abs_return"), how="left")
    df = df.dropna(subset=["realized_abs_return"]).copy()

    event_rows = df[df["event"]]
    non_event_rows = df[~df["event"]]

    return {"threshold": threshold, "hold_days": hold, "events": _stats(event_rows["realized_abs_return"]), "non_events": _stats(non_event_rows["realized_abs_return"]) }


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument("--gdelt", required=True)
    p.add_argument("--prices", required=True)
    p.add_argument("--threshold", type=float, default=2.0)
    p.add_argument("--hold", type=int, default=3)
    args = p.parse_args(argv)

    out = evaluate(pathlib.Path(args.gdelt), pathlib.Path(args.prices), args.threshold, args.hold)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
