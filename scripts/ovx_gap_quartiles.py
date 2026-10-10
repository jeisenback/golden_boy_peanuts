#!/usr/bin/env python3
"""
Quartile study: does the OVX-vs-realized vol gap predict the next 10-day move, and does
that move beat what options had already priced in? (#212, #217)

For each trading day the script computes:

    gap               = OVX/100 - 20-day realized vol
    fwd_move_pct      = |10-trading-day log return| * 100
    implied_move_pct  = OVX/100 * sqrt(10/252) * sqrt(2/pi) * 100
    ratio             = fwd_move_pct / implied_move_pct

implied_move_pct is the *expected absolute move* under a normal distribution, which is
what a long straddle's fair premium pays for. Under fair pricing the mean ratio is 1.0,
the median is about 0.85 and the share of days above 1.0 is about 0.42; those are the
baselines printed in the report.

Days whose realized-vol window or forward horizon touch a non-positive close
(WTI, April 2020) are excluded.

Closes for CL=F come from FRED WTI spot (DCOILWTICO); other tickers use yfinance.

Usage:
    python scripts/ovx_gap_quartiles.py [--start 2020-01-01] [--ticker CL=F]
                                        [--report docs/backtest_reports/<auto>.md]
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
import logging
import math
from pathlib import Path
import statistics
import sys
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.ovx_loader import (
    fetch_closes_yfinance,
    historical_volatility_gap,
    load_ovx,
)
from src.backtest.wti_loader import load_wti

REPORT_DIR = Path("docs/backtest_reports")
_WTI_TICKER = "CL=F"
_LOOKBACK_DAYS = 30
_FORWARD_TRADING_DAYS = 10
_TRADING_DAYS_PER_YEAR = 252
# Normal-distribution constants for the fair-pricing baselines shown in the report.
_EXPECTED_ABS_Z = math.sqrt(2.0 / math.pi)  # E|Z| for Z ~ N(0,1)
_HALF_NORMAL_MEDIAN = 0.6745  # median of |Z| for Z ~ N(0,1)
_FAIR_MEDIAN_RATIO = _HALF_NORMAL_MEDIAN / _EXPECTED_ABS_Z
_FAIR_SHARE_ABOVE_ONE = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(_EXPECTED_ABS_Z / math.sqrt(2.0))))
# Verdict bands from docs/plans/actionable-signal-plan.md, step 1 (applied to Q4 mean ratio).
_VERDICT_ALIVE_ABOVE = 1.10
_VERDICT_LOSES_BELOW = 0.90

logger = logging.getLogger(__name__)


class StudyRow(NamedTuple):
    as_of: date
    gap: float
    fwd_move_pct: float
    implied_move_pct: float
    ratio: float


class QuartileStats(NamedTuple):
    label: str
    gap_lo: float
    gap_hi: float
    mean_fwd_move_pct: float
    mean_ratio: float
    median_ratio: float
    share_ratio_above_one: float
    n: int


def implied_move_pct(implied_vol: float, *, horizon_trading_days: int) -> float:
    """
    Expected absolute move (%) over the horizon for an annualized vol fraction.

    Args:
        implied_vol: Annualized implied volatility as a fraction (OVX 32 -> 0.32).
        horizon_trading_days: Forward horizon in trading days.

    Returns:
        sigma * sqrt(horizon / 252) * sqrt(2 / pi) * 100, the mean |move| a straddle's
        fair premium pays for under normal returns.
    """
    return (
        implied_vol
        * math.sqrt(horizon_trading_days / _TRADING_DAYS_PER_YEAR)
        * _EXPECTED_ABS_Z
        * 100.0
    )


def build_rows(ticker: str, *, ovx: dict[date, float], closes: dict[date, float]) -> list[StudyRow]:
    """
    One StudyRow per OVX date with a valid gap and a full forward window.

    Args:
        ticker: Instrument label passed through to the VolatilityGap record.
        ovx: OVX closes by date (index points, e.g. 32.5).
        closes: Daily closes by date for `ticker`; non-positive values mark bad days.

    Returns:
        Rows in ascending as_of order. Dates whose lookback or forward window touches
        a non-positive close, or whose gap cannot be computed, are skipped and logged.
    """
    bad_days = [d for d, c in closes.items() if c <= 0.0]
    valid_dates = sorted(d for d, c in closes.items() if c > 0.0)
    index_of = {d: i for i, d in enumerate(valid_dates)}

    rows: list[StudyRow] = []
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
            vg = historical_volatility_gap(ticker, as_of, closes=closes, ovx=ovx)
        except ValueError as exc:
            logger.debug("Skipping %s for %s: %s", as_of, ticker, exc)
            continue
        fwd = abs(math.log(closes[fwd_date] / closes[as_of])) * 100.0
        implied = implied_move_pct(vg.implied_vol, horizon_trading_days=_FORWARD_TRADING_DAYS)
        rows.append(StudyRow(as_of, vg.gap, fwd, implied, fwd / implied))
    return rows


def summarize_quartiles(rows: list[StudyRow]) -> list[QuartileStats]:
    """
    Sort rows by gap, split into four equal buckets, summarize each.

    Args:
        rows: StudyRows in any order; at least four.

    Returns:
        Four QuartileStats, Q1 (most negative gap) to Q4 (widest positive gap).
    """
    ordered = sorted(rows, key=lambda r: r.gap)
    n = len(ordered)
    out: list[QuartileStats] = []
    for k in range(4):
        q = ordered[k * n // 4 : (k + 1) * n // 4]
        ratios = [r.ratio for r in q]
        out.append(
            QuartileStats(
                label=f"Q{k + 1}",
                gap_lo=q[0].gap,
                gap_hi=q[-1].gap,
                mean_fwd_move_pct=statistics.mean(r.fwd_move_pct for r in q),
                mean_ratio=statistics.mean(ratios),
                median_ratio=statistics.median(ratios),
                share_ratio_above_one=sum(1 for x in ratios if x > 1.0) / len(ratios),
                n=len(q),
            )
        )
    return out


def verdict(q4_mean_ratio: float) -> str:
    """
    Map the top-quartile mean ratio onto the plan's three verdict bands.

    Args:
        q4_mean_ratio: Mean realized/implied ratio for the widest-gap quartile.

    Returns:
        One of three verdict strings; the leading capitalized phrase is stable for tests.
    """
    if q4_mean_ratio > _VERDICT_ALIVE_ABOVE:
        return (
            "STRADDLE THESIS ALIVE: realized move beats the priced-in move in the top gap "
            "quartile; #134 straddle weights may lean on vol gap as written."
        )
    if q4_mean_ratio < _VERDICT_LOSES_BELOW:
        return (
            "BUYING VOL LOSES TO PREMIUM: top-quartile realized move does not cover the "
            "priced-in move; #134 pivots to directional spreads."
        )
    return (
        "INDETERMINATE: within the 0.90-1.10 band; hold #134, posture stays "
        '"research shortlist".'
    )


def _ranks(values: list[float]) -> list[float]:
    """Average ranks for Spearman (ties share the mean rank)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def render_report(
    *,
    ticker: str,
    rows: list[StudyRow],
    start: date,
    end: date,
    bad_days: list[date],
    rho: float,
) -> str:
    """Markdown report: quartile table, fair-pricing baselines, verdict, caveats."""
    stats = summarize_quartiles(rows)
    all_ratios = [r.ratio for r in rows]
    lines = [
        f"# OVX volatility-gap quartile study — {ticker} (issues #212, #217)",
        "",
        f"Generated {end.isoformat()} by `scripts/ovx_gap_quartiles.py --ticker {ticker}`.",
        "",
        f"- Sample: {len(rows)} trading days, {start.isoformat()} to {end.isoformat()}, {ticker}",
        f"- Excluded: any day whose {_LOOKBACK_DAYS}-day lookback or "
        f"{_FORWARD_TRADING_DAYS}-day forward window touches a non-positive close "
        f"({len(bad_days)} such close(s): "
        f"{', '.join(d.isoformat() for d in sorted(bad_days)) or 'none'})",
        "- gap = OVX/100 - 20-day realized vol; fwd move = |10-trading-day log return| (%)",
        "- implied move = OVX/100 * sqrt(10/252) * sqrt(2/pi) * 100, the expected absolute "
        "move a straddle's fair premium pays for; ratio = fwd move / implied move",
        "",
        "| Quartile | Gap range | Mean fwd move % | Mean ratio | Median ratio "
        "| Share ratio > 1 | N |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for s in stats:
        lines.append(
            f"| {s.label} | {s.gap_lo:+.3f} to {s.gap_hi:+.3f} | {s.mean_fwd_move_pct:.2f} | "
            f"{s.mean_ratio:.3f} | {s.median_ratio:.3f} | {s.share_ratio_above_one:.3f} | {s.n} |"
        )
    lines += [
        f"| All | {stats[0].gap_lo:+.3f} to {stats[-1].gap_hi:+.3f} | "
        f"{statistics.mean(r.fwd_move_pct for r in rows):.2f} | "
        f"{statistics.mean(all_ratios):.3f} | {statistics.median(all_ratios):.3f} | "
        f"{sum(1 for x in all_ratios if x > 1.0) / len(all_ratios):.3f} | {len(rows)} |",
        "",
        f"Fair-pricing baseline (normal returns, options priced exactly right): mean ratio 1.000, "
        f"median ratio {_FAIR_MEDIAN_RATIO:.3f}, share > 1 of {_FAIR_SHARE_ABOVE_ONE:.3f}. "
        "Read each quartile against those, not against zero.",
        "",
        f"Spearman rank correlation, gap vs forward move: {rho:+.3f}",
        "",
        "## Verdict (plan step 1, applied to Q4 mean ratio)",
        "",
        f"Q4 mean ratio {stats[3].mean_ratio:.3f} -> {verdict(stats[3].mean_ratio)}",
        "",
        "## Caveats",
        "- Overlapping 10-day windows make observations serially correlated; "
        "treat the differences as descriptive, not statistically tested.",
        "- Continuous futures contain contract rolls that add noise to realized vol; "
        "an ETF proxy adds roll yield and tracking error instead.",
        "- OVX is a crude-wide implied-vol proxy, not the ticker's own option chain; "
        "no option P&L is reconstructed.",
        "- The implied leg assumes normal returns; fat tails raise the fair mean ratio above 1.",
    ]
    return "\n".join(lines) + "\n"


def fetch_closes(ticker: str, start: date, end: date) -> dict[date, float]:
    """Return daily closes: FRED WTI spot for CL=F, yfinance for any other ticker."""
    if ticker == _WTI_TICKER:
        return load_wti(start, end)
    return fetch_closes_yfinance(ticker, start, end)


def _default_report_path(ticker: str) -> Path:
    safe = ticker.replace("=", "").replace("^", "")
    return REPORT_DIR / f"217-ovx-gap-ratio-{safe}.md"


def main() -> int:
    """Run the study for one ticker and write the report.

    Returns 0 on success, 1 if the live data fetch fails or too few rows survive.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--ticker", default="CL=F")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    start = date.fromisoformat(args.start)
    end = datetime.now(tz=UTC).date()
    report_path: Path = args.report or _default_report_path(args.ticker)
    logging.getLogger("src.backtest.ovx_loader").setLevel(logging.ERROR)

    try:
        ovx = load_ovx(start, end)
        closes = fetch_closes(args.ticker, start - timedelta(days=60), end)
    except Exception:
        logger.exception("ovx_gap_quartiles: live data fetch failed; no report written")
        return 1

    rows = build_rows(args.ticker, ovx=ovx, closes=closes)
    if len(rows) < 4:
        logger.error("ovx_gap_quartiles: only %d usable rows; no report written", len(rows))
        return 1
    bad_days = [d for d, c in closes.items() if c <= 0.0]
    rho = statistics.correlation(
        _ranks([r.gap for r in rows]), _ranks([r.fwd_move_pct for r in rows])
    )

    text = render_report(
        ticker=args.ticker, rows=rows, start=start, end=end, bad_days=bad_days, rho=rho
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
