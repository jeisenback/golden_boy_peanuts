"""
Ingestion Agent

Responsibilities (Design Doc Section 4, PRD Section 4.1):
  - Fetch crude prices (WTI, Brent) from Alpha Vantage
  - Fetch ETF/equity prices (USO, XLE, XOM, CVX) from yfinance
  - Fetch options chain data from Yahoo Finance / Polygon.io
  - Validate all inbound data via Pydantic models at the boundary
  - Normalize into a unified MarketState object
  - Persist to PostgreSQL; quarantine malformed records, never drop silently
  - Emit structured JSON logs throughout

ESOD constraints: Python 3.11+, type hints on all public functions,
no langchain.*/langgraph.* imports, tenacity on all external API calls,
DATABASE_URL from environment.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import math
import os

import requests
from sqlalchemy.engine import Engine
import yfinance as yf

from src.agents.ingestion.db import write_option_records, write_price_records
from src.agents.ingestion.models import (
    InstrumentType,
    MarketState,
    OptionRecord,
    RawPriceRecord,
)
from src.core.db import get_engine
from src.core.retry import with_retry

# Do NOT call logging.basicConfig() here — configuration belongs in the entry point.
logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS: int = 10  # seconds; applies to all outbound HTTP requests

# Canonical ETF/equity universe for Sprint 3 ingestion (PRD §4.1); update alongside issue #11
_ETF_EQUITY_INSTRUMENTS: list[tuple[str, InstrumentType]] = [
    ("USO", InstrumentType.ETF),
    ("XLE", InstrumentType.ETF),
    ("XOM", InstrumentType.EQUITY),
    ("CVX", InstrumentType.EQUITY),
]

# Number of nearest expiry dates fetched per instrument for options chain (PRD §4.1)
_OPTIONS_EXPIRY_LIMIT: int = 2

# Milliseconds per second — used to convert timedelta.total_seconds() to ms
_MS_PER_SECOND: int = 1000

# Ticker symbols derived from the ETF/equity universe; passed to fetch_options_chain()
_ETF_EQUITY_SYMBOLS: list[str] = [symbol for symbol, _ in _ETF_EQUITY_INSTRUMENTS]


def _nan_to_none_float(val: object) -> float | None:
    """Return None if val is None or NaN; otherwise return float(val)."""
    if val is None:
        return None
    try:
        f = float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _nan_to_none_int(val: object) -> int | None:
    """Return None if val is None or NaN; otherwise return int(float(val))."""
    f = _nan_to_none_float(val)
    return None if f is None else int(f)


@with_retry()
def fetch_crude_prices() -> list[RawPriceRecord]:
    """
    Fetch current WTI and Brent crude prices from Alpha Vantage.

    Calls the GLOBAL_QUOTE endpoint for CL=F (WTI) and BZ=F (Brent).
    Timestamp is set to UTC time of the fetch, not the API's reported quote time.

    Returns:
        Validated RawPriceRecord objects for WTI (CL=F) and Brent (BZ=F).

    Raises:
        RuntimeError: If ALPHA_VANTAGE_API_KEY env var is not set.
        ValueError: If any API response is missing required price fields.
        Exception: Propagates the last exception after all retry attempts
            are exhausted (reraise=True).
    """
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("ALPHA_VANTAGE_API_KEY environment variable is not set.")

    symbols = ["CL=F", "BZ=F"]
    records: list[RawPriceRecord] = []
    fetch_time = datetime.now(timezone.utc)

    for symbol in symbols:
        response = requests.get(
            "https://www.alphavantage.co/query",
            params={"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": api_key},
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data: dict[str, object] = response.json()

        quote = data.get("Global Quote", {})
        price_str = quote.get("05. price") if isinstance(quote, dict) else None
        if not price_str:
            raise ValueError(f"Malformed Alpha Vantage response for {symbol}: {data}")

        volume_str = quote.get("06. volume") if isinstance(quote, dict) else None
        volume: int | None = int(volume_str) if volume_str else None

        try:
            records.append(
                RawPriceRecord(
                    instrument=symbol,
                    instrument_type=InstrumentType.CRUDE_FUTURES,
                    price=float(price_str),
                    volume=volume,
                    timestamp=fetch_time,
                    source="alpha_vantage",
                )
            )
        except Exception as exc:
            raise ValueError(f"Malformed Alpha Vantage response for {symbol}: {data}") from exc

    return records


@with_retry()
def fetch_etf_equity_prices() -> list[RawPriceRecord]:
    """
    Fetch current prices for USO, XLE, XOM, and CVX from Yahoo Finance via yfinance.

    Uses yfinance.Ticker.fast_info for minimal-latency price retrieval.
    Timestamp is set to the UTC time of the fetch call, not the market data timestamp.

    If any individual ticker fetch fails, the exception is logged then re-raised.
    Degraded-mode behavior (continuing with remaining tickers) is the responsibility
    of the caller (run_ingestion), not this function.

    Returns:
        Validated RawPriceRecord objects for USO, XLE, XOM, and CVX.

    Raises:
        ValueError: If a ticker returns a missing or non-positive price.
        Exception: Propagates the last exception after all retry attempts are
            exhausted (reraise=True via with_retry).
    """
    records: list[RawPriceRecord] = []
    fetch_time = datetime.now(timezone.utc)

    for symbol, instrument_type in _ETF_EQUITY_INSTRUMENTS:
        try:
            fast_info = yf.Ticker(symbol).fast_info
            price = fast_info.last_price
            if price is None or price <= 0:
                raise ValueError(f"Invalid price from yfinance for {symbol}: {price!r}")
            raw_vol = getattr(fast_info, "last_volume", None)
            volume: int | None = int(raw_vol) if raw_vol is not None else None
            records.append(
                RawPriceRecord(
                    instrument=symbol,
                    instrument_type=instrument_type,
                    price=float(price),
                    volume=volume,
                    timestamp=fetch_time,
                    source="yfinance",
                )
            )
        except Exception:
            logger.exception("Failed to fetch price for %s via yfinance", symbol)
            if records:
                logger.warning(
                    "Discarding %d already-fetched record(s) due to failure on %s",
                    len(records),
                    symbol,
                )
            raise

    return records


@with_retry()
def fetch_options_chain(instruments: list[str]) -> list[OptionRecord]:
    """
    Fetch options chain data for the given instruments from Yahoo Finance via yfinance.

    If POLYGON_API_KEY is not set, logs a WARNING and falls back to yfinance.
    For each instrument, fetches the nearest _OPTIONS_EXPIRY_LIMIT expiry dates and
    iterates over all call and put contracts in each chain.

    Records with missing or NaN implied_volatility are included with
    implied_volatility=None (not filtered out) — Feature Generation handles absent IV.

    Args:
        instruments: List of ticker symbols to fetch options for,
            e.g. ["USO", "XLE", "XOM", "CVX"].

    Returns:
        Validated OptionRecord objects for all instruments, expiries, and option types.

    Raises:
        Exception: Propagates any yfinance exception after all retry attempts
            are exhausted (reraise=True via with_retry). Caller implements
            degraded-mode behavior.
    """
    if not os.environ.get("POLYGON_API_KEY"):
        logger.warning("POLYGON_API_KEY not set; falling back to yfinance for options chain data")

    records: list[OptionRecord] = []
    fetch_time = datetime.now(timezone.utc)

    for symbol in instruments:
        ticker = yf.Ticker(symbol)
        expiries: tuple[str, ...] = ticker.options

        for expiry_str in expiries[:_OPTIONS_EXPIRY_LIMIT]:
            expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            chain = ticker.option_chain(expiry_str)

            for option_type, df in (("call", chain.calls), ("put", chain.puts)):
                for _, row in df.iterrows():
                    iv = _nan_to_none_float(row.get("impliedVolatility"))
                    oi = _nan_to_none_int(row.get("openInterest"))
                    vol = _nan_to_none_int(row.get("volume"))

                    records.append(
                        OptionRecord(
                            instrument=symbol,
                            strike=float(row["strike"]),
                            expiration_date=expiry_dt,
                            implied_volatility=iv,
                            open_interest=oi,
                            volume=vol,
                            option_type=option_type,
                            timestamp=fetch_time,
                            source="yfinance",
                        )
                    )

    return records


def run_ingestion() -> MarketState:
    """
    Execute one full ingestion cycle.

    Calls fetch_crude_prices(), fetch_etf_equity_prices(), and fetch_options_chain()
    in independent try/except blocks so one feed failure does not abort the others.
    Persists all successfully fetched records to PostgreSQL; DB write failures are
    also caught and recorded rather than propagated.

    Emits a structured JSON log at cycle end with price_records, option_records,
    error_count, and duration_ms.

    Returns:
        MarketState with prices, options, and ingestion_errors populated.
        ingestion_errors is the ESOD-4 structured error response: callers MUST
        inspect it to distinguish feed timeouts from DB outages. An empty list
        indicates a fully successful cycle.
        Never raises — even total feed failure returns an empty-but-valid state.
    """
    start_time = datetime.now(timezone.utc)
    prices: list[RawPriceRecord] = []
    options: list[OptionRecord] = []
    errors: list[str] = []

    # --- Fetch feeds (each isolated so one failure cannot abort the others) ---
    try:
        prices.extend(fetch_crude_prices())
    except Exception as exc:
        logger.exception("fetch_crude_prices failed")
        errors.append(f"fetch_crude_prices: {exc}")

    try:
        prices.extend(fetch_etf_equity_prices())
    except Exception as exc:
        logger.exception("fetch_etf_equity_prices failed")
        errors.append(f"fetch_etf_equity_prices: {exc}")

    instruments = _ETF_EQUITY_SYMBOLS
    try:
        options.extend(fetch_options_chain(instruments))
    except Exception as exc:
        logger.exception("fetch_options_chain failed")
        errors.append(f"fetch_options_chain: {exc}")

    # --- Persist to PostgreSQL ---
    _engine: Engine | None = None
    try:
        _engine = get_engine()
    except Exception as exc:
        logger.exception("Failed to acquire DB engine — skipping persistence")
        errors.append(f"get_engine: {exc}")

    if _engine is not None and prices:
        try:
            write_price_records(prices, _engine)
        except Exception as exc:
            logger.exception("write_price_records failed; price records not persisted")
            errors.append(f"write_price_records: {exc}")

    if _engine is not None and options:
        try:
            write_option_records(options, _engine)
        except Exception as exc:
            logger.exception("write_option_records failed; option records not persisted")
            errors.append(f"write_option_records: {exc}")

    # --- Assemble MarketState ---
    snapshot_time = datetime.now(timezone.utc)
    state = MarketState(
        snapshot_time=snapshot_time,
        prices=prices,
        options=options,
        ingestion_errors=errors,
    )

    # --- Structured cycle log ---
    duration_ms = int((snapshot_time - start_time).total_seconds() * _MS_PER_SECOND)
    logger.info(
        json.dumps(
            {
                "event": "ingestion_cycle_complete",
                "price_records": len(prices),
                "option_records": len(options),
                "error_count": len(errors),
                "duration_ms": duration_ms,
            }
        )
    )

    return state
