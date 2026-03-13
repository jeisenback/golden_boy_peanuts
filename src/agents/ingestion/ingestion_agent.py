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

from datetime import UTC, datetime
import logging
import os

import requests
import yfinance as yf

from src.agents.ingestion.db import write_option_records  # noqa: F401
from src.agents.ingestion.models import (
    InstrumentType,
    MarketState,
    OptionRecord,
    RawPriceRecord,
)
from src.core.retry import with_retry

# Do NOT call logging.basicConfig() here — configuration belongs in the entry point.
logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS: int = 10  # seconds; applies to all outbound HTTP requests

# Instrument classification for the ETF/equity feed
_ETF_EQUITY_INSTRUMENTS: list[tuple[str, InstrumentType]] = [
    ("USO", InstrumentType.ETF),
    ("XLE", InstrumentType.ETF),
    ("XOM", InstrumentType.EQUITY),
    ("CVX", InstrumentType.EQUITY),
]


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
    fetch_time = datetime.now(UTC)

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
    fetch_time = datetime.now(UTC)

    for symbol, instrument_type in _ETF_EQUITY_INSTRUMENTS:
        try:
            fast_info = yf.Ticker(symbol).fast_info
            price = fast_info.last_price
            if price is None or price <= 0:
                raise ValueError(
                    f"Invalid price from yfinance for {symbol}: {price!r}"
                )
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
            raise

    return records


@with_retry()
def fetch_options_chain() -> list[OptionRecord]:
    """
    Fetch options chain data for USO, XLE, XOM, CVX from Yahoo Finance / Polygon.io.

    Retries with exponential backoff (ESOD Section 6).
    On persistent failure, re-raises — caller implements degraded-mode behavior.

    Returns:
        Validated OptionRecord objects for all configured instruments.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "fetch_options_chain not yet implemented. "
        "TODO: Fetch options chain for USO, XLE, XOM, CVX. "
        "Sources: Yahoo Finance (yfinance) or Polygon.io. "
        "Validate each record with OptionRecord before returning. "
        "Results are written to DB via write_option_records. "
        "See .env.example for POLYGON_API_KEY."
    )


def run_ingestion() -> MarketState:
    """
    Execute one full ingestion cycle.

    Fetches all configured data sources, validates via Pydantic,
    normalizes into a MarketState, and persists to PostgreSQL.

    On partial failure (one feed unavailable), continues with available data
    and logs the failure. The pipeline must not stop on a single feed failure
    (ESOD Section 6 — degraded-mode output).

    Returns:
        MarketState representing the current market snapshot.
        ingestion_errors contains details of any failed/quarantined records.

    Raises:
        RuntimeError: If DATABASE_URL is not set.
    """
    raise NotImplementedError(
        "run_ingestion not yet implemented. "
        "TODO: Orchestrate fetch_crude_prices, fetch_etf_equity_prices, "
        "fetch_options_chain. Catch individual feed failures and continue. "
        "Build MarketState. Persist to DB via "
        "src.agents.ingestion.db.write_price_records and "
        "src.agents.ingestion.db.write_option_records."
    )
