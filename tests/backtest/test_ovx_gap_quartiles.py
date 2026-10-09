"""
Unit tests for the pure functions in scripts/ovx_gap_quartiles.py (issue #217).

All tests run offline on synthetic closes and OVX series. The study asks whether
the realized 10-day move beats the move options had already priced in, so the
implied leg is the *expected absolute move* under a normal: sigma * sqrt(t) * sqrt(2/pi).
Under fair pricing the mean ratio is 1.0 by construction.
"""

from __future__ import annotations

from datetime import date, timedelta
import math
import pathlib as _pathlib
import sys as _sys

import pytest

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
from scripts.ovx_gap_quartiles import (  # type: ignore[import]
    _FORWARD_TRADING_DAYS,
    StudyRow,
    build_rows,
    implied_move_pct,
    render_report,
    summarize_quartiles,
    verdict,
)


def _business_days(start: date, n: int) -> list[date]:
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _synthetic_series(
    n_days: int = 80, ovx_level: float = 40.0, bad_day_index: int | None = None
) -> tuple[dict[date, float], dict[date, float], list[date]]:
    """Alternating +1%/-1% closes so realized vol is well defined; constant OVX."""
    days = _business_days(date(2024, 1, 1), n_days)
    closes: dict[date, float] = {}
    price = 70.0
    for i, d in enumerate(days):
        price *= 1.01 if i % 2 == 0 else 0.99
        closes[d] = price
    if bad_day_index is not None:
        closes[days[bad_day_index]] = -1.0
    ovx = dict.fromkeys(days, ovx_level)
    return closes, ovx, days


def test_implied_move_pct_is_expected_absolute_move_over_horizon() -> None:
    implied_vol = 0.32  # OVX at 32
    expected = 0.32 * math.sqrt(10 / 252) * math.sqrt(2 / math.pi) * 100.0
    assert implied_move_pct(implied_vol, horizon_trading_days=10) == pytest.approx(expected)


def test_build_rows_ratio_is_realized_over_implied_for_each_as_of() -> None:
    closes, ovx, days = _synthetic_series(ovx_level=40.0)
    rows = build_rows("CL=F", ovx=ovx, closes=closes)

    assert rows, "expected at least one row from an 80-day synthetic series"
    by_date = {r.as_of: r for r in rows}
    as_of = days[40]
    row = by_date[as_of]
    fwd_date = days[40 + _FORWARD_TRADING_DAYS]
    expected_fwd = abs(math.log(closes[fwd_date] / closes[as_of])) * 100.0
    expected_implied = implied_move_pct(0.40, horizon_trading_days=_FORWARD_TRADING_DAYS)

    assert row.fwd_move_pct == pytest.approx(expected_fwd)
    assert row.implied_move_pct == pytest.approx(expected_implied)
    assert row.ratio == pytest.approx(expected_fwd / expected_implied)


def test_build_rows_drops_windows_touching_a_non_positive_close() -> None:
    closes, ovx, days = _synthetic_series(bad_day_index=50)
    rows = build_rows("CL=F", ovx=ovx, closes=closes)
    bad = days[50]

    for r in rows:
        fwd_date = days[days.index(r.as_of) + _FORWARD_TRADING_DAYS]
        assert not (
            r.as_of - timedelta(days=30) <= bad <= fwd_date + timedelta(days=1)
        ), f"row {r.as_of} overlaps the bad close on {bad}"


def test_summarize_quartiles_reports_mean_median_and_share_above_one() -> None:
    # Eight rows sorted by gap -> four quartiles of two. Only Q4 ratios matter here.
    ratios = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.5, 0.5]
    rows = [
        StudyRow(
            as_of=date(2024, 1, 1) + timedelta(days=i),
            gap=i / 10.0,
            fwd_move_pct=r * 5.0,
            implied_move_pct=5.0,
            ratio=r,
        )
        for i, r in enumerate(ratios)
    ]
    stats = summarize_quartiles(rows)

    assert len(stats) == 4
    q4 = stats[3]
    assert q4.n == 2
    assert q4.gap_lo == pytest.approx(0.6)
    assert q4.gap_hi == pytest.approx(0.7)
    assert q4.mean_ratio == pytest.approx(1.0)
    assert q4.median_ratio == pytest.approx(1.0)
    assert q4.share_ratio_above_one == pytest.approx(0.5)
    assert q4.mean_fwd_move_pct == pytest.approx(5.0)


@pytest.mark.parametrize(
    ("mean_ratio", "expected_prefix"),
    [
        (1.25, "STRADDLE THESIS ALIVE"),
        (1.10, "INDETERMINATE"),
        (1.00, "INDETERMINATE"),
        (0.90, "INDETERMINATE"),
        (0.75, "BUYING VOL LOSES TO PREMIUM"),
    ],
)
def test_verdict_bands_match_the_plan(mean_ratio: float, expected_prefix: str) -> None:
    assert verdict(mean_ratio).startswith(expected_prefix)


def test_render_report_names_ticker_baselines_and_verdict() -> None:
    rows = [
        StudyRow(
            as_of=date(2024, 1, 1) + timedelta(days=i),
            gap=i / 10.0,
            fwd_move_pct=6.0,
            implied_move_pct=5.0,
            ratio=1.2,
        )
        for i in range(8)
    ]
    text = render_report(
        ticker="USO",
        rows=rows,
        start=date(2024, 1, 1),
        end=date(2024, 1, 12),
        bad_days=[],
        rho=0.1,
    )

    assert "USO" in text
    assert "mean ratio" in text.lower()
    assert "fair-pricing baseline" in text.lower()
    assert "STRADDLE THESIS ALIVE" in text
    assert "no option P&L is reconstructed" in text
