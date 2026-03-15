"""
backfill_prices.py — seed market_prices with 30 days of historical daily closes.

Fetches daily OHLC history from yfinance for all pipeline instruments and
inserts the closing prices into market_prices, skipping any rows that already
exist for that instrument + timestamp (idempotent).

Usage:
    DATABASE_URL=postgresql+psycopg2://... python scripts/backfill_prices.py
    DATABASE_URL=postgresql+psycopg2://... python scripts/backfill_prices.py --days 60

Instruments:
    Equities/ETFs : USO, XLE, XOM, CVX  (instrument_type = etf / equity)
    Crude futures : CL=F (WTI), BZ=F (Brent)  (instrument_type = crude_futures)

After this script completes, the next pipeline run will have enough price
history (≥ 10 records) to compute realized volatility and produce candidates.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import logging
import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
import yfinance as yf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Instrument registry
# ---------------------------------------------------------------------------
_INSTRUMENTS: dict[str, str] = {
    "USO": "etf",
    "XLE": "etf",
    "XOM": "equity",
    "CVX": "equity",
    "CL=F": "crude_futures",
    "BZ=F": "crude_futures",
}

_DEFAULT_DAYS: int = 30  # trading days of history to seed


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _get_engine() -> Engine:
    """Create SQLAlchemy engine from DATABASE_URL environment variable.

    Returns:
        Connected SQLAlchemy Engine.

    Raises:
        RuntimeError: If DATABASE_URL is not set.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    return create_engine(url)


def _fetch_history(ticker: str, days: int) -> list[tuple[datetime, float, int | None]]:
    """Fetch daily closing prices from yfinance for the past `days` calendar days.

    Args:
        ticker: yfinance ticker symbol, e.g. 'USO' or 'CL=F'.
        days: Number of calendar days of history to request (fetches ~days/7*5
              trading days).

    Returns:
        List of (timestamp_utc, close_price, volume) tuples, oldest first.
        Volume may be None if unavailable.
    """
    # Fetch slightly more calendar days to ensure we get `days` trading days
    end = datetime.now(tz=UTC).date()
    start = end - timedelta(days=int(days * 1.5))

    df = yf.Ticker(ticker).history(start=str(start), end=str(end), interval="1d")
    if df.empty:
        logger.warning("yfinance returned no history for %s", ticker)
        return []

    rows: list[tuple[datetime, float, int | None]] = []
    for ts, row in df.iterrows():
        # yfinance index is timezone-aware; normalize to UTC
        if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
            ts_utc = ts.to_pydatetime().astimezone(UTC)
        else:
            ts_utc = ts.to_pydatetime().replace(tzinfo=UTC)

        close = float(row["Close"])
        vol = int(row["Volume"]) if row["Volume"] and row["Volume"] == row["Volume"] else None
        rows.append((ts_utc, close, vol))

    # Return only the most recent `days` trading days
    return rows[-days:]


def _insert_prices(
    engine: Engine,
    ticker: str,
    instrument_type: str,
    rows: list[tuple[datetime, float, int | None]],
) -> int:
    """Insert price rows, skipping duplicates by (instrument, timestamp).

    Args:
        engine: SQLAlchemy Engine connected to the target database.
        ticker: Instrument ticker symbol.
        instrument_type: Raw type string, e.g. 'etf' or 'crude_futures'.
        rows: List of (timestamp_utc, close_price, volume) tuples.

    Returns:
        Number of rows actually inserted (duplicates skipped).
    """
    if not rows:
        return 0

    sql = text("""
        INSERT INTO market_prices
            (instrument, instrument_type, price, volume, source, timestamp)
        VALUES
            (:instrument, :instrument_type, :price, :volume, :source, :timestamp)
        ON CONFLICT DO NOTHING
    """)

    params = [
        {
            "instrument": ticker,
            "instrument_type": instrument_type,
            "price": close,
            "volume": vol,
            "source": "yfinance_backfill",
            "timestamp": ts,
        }
        for ts, close, vol in rows
    ]

    with engine.begin() as conn:
        result = conn.execute(sql, params)

    inserted: int = result.rowcount if result.rowcount >= 0 else len(rows)
    return inserted


def backfill(days: int = _DEFAULT_DAYS) -> None:
    """Seed market_prices with `days` trading days of history for all instruments.

    Args:
        days: Number of trading days to backfill per instrument.
    """
    engine = _get_engine()

    total_inserted = 0
    for ticker, instrument_type in _INSTRUMENTS.items():
        logger.info("Fetching %d days of history for %s ...", days, ticker)
        rows = _fetch_history(ticker, days)
        if not rows:
            logger.warning("No history returned for %s — skipping", ticker)
            continue

        inserted = _insert_prices(engine, ticker, instrument_type, rows)
        logger.info(
            "%s: %d row(s) fetched, %d inserted (duplicates skipped)",
            ticker,
            len(rows),
            inserted,
        )
        total_inserted += inserted

    logger.info("Backfill complete. Total rows inserted: %d", total_inserted)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Parse args and run backfill.

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=_DEFAULT_DAYS,
        help=f"Trading days of history to seed (default: {_DEFAULT_DAYS})",
    )
    args = parser.parse_args()

    try:
        backfill(days=args.days)
    except Exception:
        logger.exception("Backfill failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
