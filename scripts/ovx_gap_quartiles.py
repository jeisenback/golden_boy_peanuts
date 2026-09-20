#!/usr/bin/env python3
"""
Quartile study: does the OVX-vs-realized vol gap predict the next 10-day CL=F move? (#212)

Days whose realized-vol window or forward horizon touch a non-positive close
(WTI, April 2020) are excluded. Writes docs/backtest_reports/212-ovx-gap-quartiles.md.

Usage: python scripts/ovx_gap_quartiles.py [--start 2020-01-01]
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
import logging
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.ovx_loader import (
    fetch_closes_yfinance,
    historical_volatility_gap,
    load_ovx,
)

REPORT_PATH = Path("docs/backtest_reports/212-ovx-gap-quartiles.md")
_LOOKBACK_DAYS = 30
_FORWARD_TRADING_DAYS = 10
logger = logging.getLogger(__name__)


def _ranks(values: list[float]) -> list[float]:
    """Return the 0-based rank of each value (ties broken by input order)."""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    for rank, idx in enumerate(order):
        ranks[idx] = float(rank)
    return ranks


def main() -> int:
    """
    Run the quartile study and write REPORT_PATH.

    Fetches OVX from FRED and CL=F closes from yfinance (both retried).

    Returns:
        0 on success, 1 if either live data fetch fails.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2020-01-01")
    args = parser.parse_args()
    start = date.fromisoformat(args.start)
    end = datetime.now(tz=UTC).date()
    logging.getLogger("src.backtest.ovx_loader").setLevel(logging.ERROR)

    try:
        ovx = load_ovx(start, end)
        closes = fetch_closes_yfinance("CL=F", start - timedelta(days=60), end)
    except Exception:
        logger.exception("ovx_gap_quartiles: live data fetch failed; no report written")
        return 1
    bad_days = [d for d, c in closes.items() if c <= 0.0]
    valid_dates = sorted(d for d, c in closes.items() if c > 0.0)
    index_of = {d: i for i, d in enumerate(valid_dates)}

    rows: list[tuple[float, float]] = []
    for as_of in sorted(ovx):
        if as_of not in index_of:
            continue
        i = index_of[as_of]
        if i + _FORWARD_TRADING_DAYS >= len(valid_dates):
            continue
        fwd_date = valid_dates[i + _FORWARD_TRADING_DAYS]
        if any(
            as_of - timedelta(days=_LOOKBACK_DAYS) <= b <= fwd_date + timedelta(days=1)
            for b in bad_days
        ):
            continue
        try:
            gap = historical_volatility_gap("CL=F", as_of, closes=closes, ovx=ovx).gap
        except ValueError:
            continue
        fwd = abs(math.log(closes[fwd_date] / closes[as_of])) * 100.0
        rows.append((gap, fwd))

    rows.sort(key=lambda r: r[0])
    n = len(rows)
    quartiles = [rows[k * n // 4 : (k + 1) * n // 4] for k in range(4)]
    gaps = [r[0] for r in rows]
    fwds = [r[1] for r in rows]
    rho = statistics.correlation(_ranks(gaps), _ranks(fwds))

    lines = [
        "# OVX volatility-gap quartile study (issue #212)",
        "",
        f"Generated {end.isoformat()} by `scripts/ovx_gap_quartiles.py`.",
        "",
        f"- Sample: {n} trading days, {start.isoformat()} to {end.isoformat()}, CL=F",
        f"- Excluded: any day whose 30-day lookback or 10-day forward window touches a "
        f"non-positive close ({len(bad_days)} such close(s): "
        f"{', '.join(d.isoformat() for d in sorted(bad_days)) or 'none'})",
        "- gap = OVX/100 - 20-day realized vol; forward move = |10-trading-day log return| (%)",
        "",
        "| Quartile | Gap range | Mean fwd move % | N |",
        "|---|---|---:|---:|",
    ]
    for k, q in enumerate(quartiles, start=1):
        lines.append(
            f"| Q{k} | {q[0][0]:+.3f} to {q[-1][0]:+.3f} | "
            f"{statistics.mean(r[1] for r in q):.2f} | {len(q)} |"
        )
    lines += [
        "",
        f"Spearman rank correlation, gap vs forward move: {rho:+.3f}",
        "",
        "## Caveats",
        "- Overlapping 10-day windows make observations serially correlated; "
        "treat the differences as descriptive, not statistically tested.",
        "- Continuous CL=F contains contract rolls that add noise to realized vol.",
        "- OVX is a crude-wide implied-vol proxy; no option P&L is reconstructed.",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
