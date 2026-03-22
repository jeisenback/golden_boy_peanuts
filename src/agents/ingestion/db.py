"""
Database read/write for the Ingestion Agent.

PostgreSQL via SQLAlchemy. Schema is TimescaleDB-compatible (ESOD Section 4.3):
all time-series tables use a 'timestamp' column for future hypertable partitioning.
DATABASE_URL read exclusively from environment variable.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.agents.ingestion.models import MarketState, OptionRecord, RawPriceRecord
from src.core.db import get_engine  # noqa: F401

logger = logging.getLogger(__name__)


def write_price_records(records: list[RawPriceRecord], engine: Engine) -> int:
    """
    Persist a batch of validated price records to market_prices table.

    Args:
        records: Validated RawPriceRecord objects to insert.
        engine: SQLAlchemy Engine for the target database.

    Returns:
        Number of records successfully written.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on constraint violation or
            connection failure after logging the exception.
    """
    if not records:
        return 0

    sql = text(
        """
        INSERT INTO market_prices (instrument, instrument_type, price, volume, source, timestamp)
        VALUES (:instrument, :instrument_type, :price, :volume, :source, :timestamp)
        """
    )
    rows = [
        {
            "instrument": r.instrument,
            "instrument_type": r.instrument_type.value,
            "price": r.price,
            "volume": r.volume,
            "source": r.source,
            "timestamp": r.timestamp,
        }
        for r in records
    ]
    try:
        with engine.begin() as conn:
            conn.execute(sql, rows)
    except Exception:
        logger.exception("write_price_records failed; %d record(s) not persisted", len(records))
        raise

    logger.info("Wrote %d price record(s) to market_prices", len(records))
    return len(records)


def write_option_records(records: list[OptionRecord], engine: Engine) -> int:
    """
    Persist a batch of validated options records to options_chain table.

    Args:
        records: Validated OptionRecord objects to insert.
        engine: SQLAlchemy Engine for the target database.

    Returns:
        Number of records successfully written.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on constraint violation or
            connection failure after logging the exception.
    """
    if not records:
        return 0

    sql = text(
        """
        INSERT INTO options_chain
            (instrument, strike, expiration_date, implied_volatility,
             open_interest, volume, option_type, source, timestamp)
        VALUES
            (:instrument, :strike, :expiration_date, :implied_volatility,
             :open_interest, :volume, :option_type, :source, :timestamp)
        """
    )
    rows = [
        {
            "instrument": r.instrument,
            "strike": r.strike,
            "expiration_date": r.expiration_date,
            "implied_volatility": r.implied_volatility,
            "open_interest": r.open_interest,
            "volume": r.volume,
            # option_type is a plain str field on OptionRecord (validated by Pydantic
            # pattern "^(call|put)$"), not an enum — no .value conversion needed.
            "option_type": r.option_type,
            "source": r.source,
            "timestamp": r.timestamp,
        }
        for r in records
    ]
    try:
        with engine.begin() as conn:
            conn.execute(sql, rows)
    except Exception:
        logger.exception("write_option_records failed; %d record(s) not persisted", len(records))
        raise

    logger.info("Wrote %d option record(s) to options_chain", len(records))
    return len(records)


def read_latest_market_state(engine: Engine) -> MarketState | None:
    """
    Read the most recent MarketState snapshot from the database.

    Args:
        engine: SQLAlchemy Engine for the target database.

    Returns:
        Most recent MarketState, or None if no data exists.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "read_latest_market_state not yet implemented. "
        "TODO: Query market_prices and options_chain for the most recent snapshot."
    )
