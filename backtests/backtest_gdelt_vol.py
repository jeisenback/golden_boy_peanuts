#!/usr/bin/env python3
"""Prototype backtest: GDELT volume spikes -> realized volatility proxy.

This is the fuller, prototype implementation originally submitted in
PR #90. It detects volume bursts using a rolling z-score on article counts
and computes forward realized absolute returns from a price series.
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
from typing import Any

import numpy as np
import pandas as pd

# Module-level defaults
DEFAULT_ROLLING_WINDOW: int = 14
ROLLING_MIN_PERIODS_FLOOR: int = 3
MIN_PERIODS_DIVISOR: int = 4
DEFAULT_ZSCORE_THRESHOLD: float = 2.0
REALIZED_RETURN_MIN_PERIODS: int = 1
DEFAULT_HOLD_DAYS: int = 3

logger = logging.getLogger(__name__)


def load_gdelt(path: pathlib.Path) -> pd.DataFrame:
    """Load a GDELT timeline CSV with a `date` and `articles` column.

    Returns a DataFrame indexed by `date` with numeric `articles`.
    """
    try:
        df = pd.read_csv(path, parse_dates=["date"]).rename(columns=str.lower)
        df = df.sort_values("date").set_index("date")
        if df.shape[0] == 0:
            raise ValueError("gdelt CSV is empty")
        if "articles" not in df.columns:
            raise KeyError("gdelt CSV must contain an 'articles' column")
        df["articles"] = pd.to_numeric(df["articles"], errors="raise")
        if df["articles"].isna().any():
            raise ValueError("gdelt 'articles' column contains NaN values")
        return df
    except Exception:
        logger.exception("Failed to load GDELT CSV: %s", path)
        raise


def load_prices(path: pathlib.Path) -> pd.DataFrame:
    """Load a price series CSV with `date` and `close` columns.

    Returns a DataFrame indexed by `date` with `close` and `ret` (pct change).
    """
    try:
        df = pd.read_csv(path, parse_dates=["date"]).rename(columns=str.lower)
        df = df.sort_values("date").set_index("date")
        if df.shape[0] == 0:
            raise ValueError("prices CSV is empty")
        if "close" not in df.columns:
            raise KeyError("prices CSV must contain a 'close' column")
        df["close"] = pd.to_numeric(df["close"], errors="raise")
        if df["close"].isna().any():
            raise ValueError("prices 'close' column contains NaN values")
        df["ret"] = df["close"].pct_change()
        return df
    except Exception:
        logger.exception("Failed to load prices CSV: %s", path)
        raise


def detect_events(
    gdelt: pd.DataFrame,
    window: int = DEFAULT_ROLLING_WINDOW,
    threshold: float = DEFAULT_ZSCORE_THRESHOLD,
) -> pd.Series:
    """Detect volume burst events using a rolling z-score on article counts."""
    s = gdelt["articles"].astype(float)
    minp = max(ROLLING_MIN_PERIODS_FLOOR, window // MIN_PERIODS_DIVISOR)
    mu = s.rolling(window=window, min_periods=minp).mean()
    sigma = s.rolling(window=window, min_periods=minp).std()
    if (sigma == 0).any():
        logger.warning("detect_events: rolling std contains zero values in window=%s; replacing with NaN", window)
        sigma = sigma.replace(0, np.nan)
    z = (s - mu) / sigma
    return z.fillna(0) > threshold


def realized_abs_return_series(prices: pd.DataFrame, hold: int) -> pd.Series:
    """Compute forward realized absolute return over the next `hold` days."""
    abs_ret = prices["ret"].abs()
    return (
        abs_ret
        .rolling(window=hold, min_periods=REALIZED_RETURN_MIN_PERIODS)
        .sum()
        .shift(-hold + 1)
    )


def _stats(s: pd.Series) -> dict[str, Any]:
    return {
        "count": int(s.count()),
        "mean": float(s.mean() if s.count() else 0.0),
        "median": float(s.median() if s.count() else 0.0),
        "std": float(s.std() if s.count() > 1 else 0.0),
    }


def evaluate(
    gdelt_path: pathlib.Path,
    prices_path: pathlib.Path,
    threshold: float,
    hold: int,
    out_events: pathlib.Path | None = None,
    plot: bool = False,
) -> dict[str, Any]:
    """Run the backtest and return summary statistics for event vs non-event returns."""
    try:
        gd = load_gdelt(gdelt_path)
        pr = load_prices(prices_path)

        events = detect_events(gd, window=DEFAULT_ROLLING_WINDOW, threshold=threshold)

        union_idx = gd.index.union(pr.index).sort_values()
        pr_reindexed = pr.reindex(union_idx).ffill()
        rv = realized_abs_return_series(pr_reindexed, hold=hold)

        df = pd.DataFrame(
            {
                "articles": gd["articles"].reindex(union_idx),
                "event": events.reindex(union_idx).fillna(False),
            }
        )
        df = df.join(pr_reindexed["close"], how="left")
        df = df.join(rv.rename("realized_abs_return"), how="left")

        df = df.dropna(subset=["realized_abs_return"]).copy()

        event_rows = df[df["event"]]
        non_event_rows = df[~df["event"]]

        out = {
            "threshold": threshold,
            "hold_days": hold,
            "events": _stats(event_rows["realized_abs_return"]),
            "non_events": _stats(non_event_rows["realized_abs_return"]),
        }

        if out_events and event_rows.shape[0] > 0:
            event_rows_to_save = event_rows[["articles", "close", "realized_abs_return"]].reset_index()
            event_rows_to_save.to_csv(out_events, index=False)

        if plot:
            try:
                import matplotlib.pyplot as plt

                fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
                ax[0].plot(df.index, df["articles"], label="articles")
                ax[0].scatter(event_rows.index, event_rows["articles"], color="red", label="events")
                ax[0].legend()
                ax[1].plot(df.index, df["realized_abs_return"], label="realized_abs_return")
                ax[1].legend()
                fig.tight_layout()
                fig_path = (
                    pathlib.Path("backtests")
                    / f"gdelt_backtest_threshold_{threshold}_hold_{hold}.png"
                )
                fig.savefig(fig_path)
            except Exception as e:
                logger.warning("Plotting failed: %s", e)

        return out
    except Exception:
        logger.exception(
            "evaluate() failed: gdelt=%s prices=%s threshold=%s hold=%s",
            gdelt_path,
            prices_path,
            threshold,
            hold,
        )
        raise


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(
        description=("Backtest prototype: GDELT volume -> realized volatility")
    )
    p.add_argument("--gdelt", required=True)
    p.add_argument("--prices", required=True)
    p.add_argument("--threshold", type=float, default=DEFAULT_ZSCORE_THRESHOLD)
    p.add_argument("--hold", type=int, default=DEFAULT_HOLD_DAYS)
    p.add_argument("--out-events", default=None, help="Path to write per-event CSV")
    p.add_argument("--plot", action="store_true", help="Save diagnostic plot to backtests/ folder")
    args = p.parse_args(argv)

    out = evaluate(
        pathlib.Path(args.gdelt),
        pathlib.Path(args.prices),
        threshold=args.threshold,
        hold=args.hold,
        out_events=pathlib.Path(args.out_events) if args.out_events else None,
        plot=args.plot,
    )

    logger.info(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
