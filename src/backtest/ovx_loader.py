"""
OVX historical implied-volatility loader for backtesting (issue #212).

The Polygon/Massive plan does not serve option prices for the COVID, Ukraine
and Houthi events, so implied vol is taken from CBOE's OVX index (daily, free,
FRED series OVXCLS) and paired with realized vol from underlying closes.

Limits: OVX is a crude-wide proxy, weak for XOM/CVX, and no option P&L is
reconstructed. Units: OVX is quoted in percent points; VolatilityGap uses
annualized fractions, so values are divided by 100 when building a gap.
"""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
import io
import logging
import math
from pathlib import Path
import statistics

from pydantic import BaseModel, Field
import requests

from src.agents.feature_generation.models import VolatilityGap
from src.core.retry import with_retry

logger = logging.getLogger(__name__)

FRED_OVX_URL: str = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_FRED_SERIES: str = "OVXCLS"
_HTTP_TIMEOUT_SECONDS: int = 30
_TRADING_DAYS_PER_YEAR: int = 252
_DEFAULT_WINDOW: int = 20
_MAX_OVX_STALENESS_DAYS: int = 5


class OvxObservation(BaseModel):
    """One validated daily OVX reading, in index (percent) points."""

    observation_date: date
    value: float = Field(..., gt=0.0)


@with_retry()
def fetch_ovx_csv(start: date, end: date) -> str:
    """
    Download the OVXCLS CSV from FRED for [start, end].

    Raises:
        requests.HTTPError: after retries are exhausted on a non-2xx response.
    """
    response = requests.get(
        FRED_OVX_URL,
        params={"id": _FRED_SERIES, "cosd": start.isoformat(), "coed": end.isoformat()},
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.text


def parse_ovx_csv(text: str) -> list[OvxObservation]:
    """
    Parse FRED OVXCLS CSV text into validated observations.

    FRED marks non-trading days with '.'; those rows (and blanks) are dropped.
    """
    observations: list[OvxObservation] = []
    for row in csv.DictReader(io.StringIO(text)):
        raw = (row.get(_FRED_SERIES) or "").strip()
        if raw in ("", "."):
            continue
        observations.append(
            OvxObservation(
                observation_date=date.fromisoformat(row["observation_date"]),
                value=float(raw),
            )
        )
    return observations


def load_ovx(
    start: date,
    end: date,
    csv_path: Path | None = None,
) -> dict[date, float]:
    """
    Return OVX index points keyed by date for start <= date <= end.

    Args:
        start:    First date to include.
        end:      Last date to include.
        csv_path: Read this local FRED-format CSV instead of calling FRED
            (used by tests and offline backtests).
    """
    text = csv_path.read_text(encoding="utf-8") if csv_path else fetch_ovx_csv(start, end)
    return {
        obs.observation_date: obs.value
        for obs in parse_ovx_csv(text)
        if start <= obs.observation_date <= end
    }


def load_closes_csv(csv_path: Path) -> dict[date, float]:
    """Load a `date,close` CSV of underlying closes into a dict."""
    with csv_path.open(newline="", encoding="utf-8") as fh:
        return {date.fromisoformat(r["date"]): float(r["close"]) for r in csv.DictReader(fh)}


@with_retry()
def fetch_closes_yfinance(ticker: str, start: date, end: date) -> dict[date, float]:
    """Fetch daily closes for [start, end] from yfinance (live path)."""
    import yfinance as yf

    frame = yf.download(
        ticker,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        progress=False,
        auto_adjust=True,
    )
    series = frame["Close"].squeeze()
    return {idx.date(): float(val) for idx, val in series.items() if not math.isnan(float(val))}


def realized_vol(
    closes: dict[date, float],
    as_of: date,
    window: int = _DEFAULT_WINDOW,
) -> float | None:
    """
    Annualized realized vol (fraction) over the last `window` returns ending at as_of.

    Non-positive closes (e.g. WTI on 2020-04-20) make log returns undefined;
    they are excluded and a WARNING is logged per excluded date.

    Returns:
        Annualized sample std-dev of log returns, or None when fewer than
        window + 1 valid closes exist on or before as_of.
    """
    history = sorted((d, c) for d, c in closes.items() if d <= as_of)
    valid = [(d, c) for d, c in history if c > 0.0]
    recent = valid[-(window + 1) :]
    if len(recent) < window + 1:
        return None

    start_of_window = recent[0][0]
    for d, c in history:
        if c <= 0.0 and d >= start_of_window:
            logger.warning(
                "realized_vol: excluding non-positive close %.2f on %s from window ending %s",
                c,
                d.isoformat(),
                as_of.isoformat(),
            )

    returns = [math.log(recent[i][1] / recent[i - 1][1]) for i in range(1, len(recent))]
    return statistics.stdev(returns) * math.sqrt(_TRADING_DAYS_PER_YEAR)


def historical_volatility_gap(
    instrument: str,
    as_of: date,
    *,
    closes: dict[date, float],
    ovx: dict[date, float],
    window: int = _DEFAULT_WINDOW,
) -> VolatilityGap:
    """
    Build a VolatilityGap for `instrument` on `as_of` using OVX as implied vol.

    Uses the latest OVX reading on or before as_of (up to 5 days back, to cover
    weekends and holidays).

    Raises:
        ValueError: if OVX is unavailable near as_of or closes are insufficient.
    """
    ovx_date = max((d for d in ovx if d <= as_of), default=None)
    if ovx_date is None or (as_of - ovx_date).days > _MAX_OVX_STALENESS_DAYS:
        raise ValueError(f"No OVX observation within {_MAX_OVX_STALENESS_DAYS} days of {as_of}")

    realized = realized_vol(closes, as_of, window)
    if realized is None:
        raise ValueError(f"Fewer than {window + 1} valid closes for {instrument} up to {as_of}")

    implied = ovx[ovx_date] / 100.0
    return VolatilityGap(
        instrument=instrument,
        realized_vol=realized,
        implied_vol=implied,
        gap=implied - realized,
        computed_at=datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC),
    )
