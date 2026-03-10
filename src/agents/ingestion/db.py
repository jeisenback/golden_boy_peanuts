"""
Database read/write for the Ingestion Agent.

PostgreSQL via SQLAlchemy. Schema is TimescaleDB-compatible (ESOD Section 4.3):
all time-series tables use a 'timestamp' column for future hypertable partitioning.
DATABASE_URL read exclusively from environment variable.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from src.agents.ingestion.models import MarketState, OptionRecord, RawPriceRecord

logger = logging.getLogger(__name__)


def get_engine() -> Engine:
    """
    Create a SQLAlchemy engine from DATABASE_URL environment variable.

    Returns:
        SQLAlchemy Engine connected to the configured PostgreSQL database.

    Raises:
        RuntimeError: If DATABASE_URL is not set.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    return create_engine(database_url, pool_pre_ping=True)


def write_price_records(records: list[RawPriceRecord], engine: Engine) -> int:
    """
    Persist a batch of validated price records to market_prices table.

    Args:
        records: Validated RawPriceRecord objects to insert.
        engine: SQLAlchemy Engine for the target database.

    Returns:
        Number of records successfully written.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "write_price_records not yet implemented. "
        "TODO: Batch INSERT into market_prices. "
        "Ensure timestamp column uses TIMESTAMPTZ for TimescaleDB compatibility."
    )


def write_option_records(records: list[OptionRecord], engine: Engine) -> int:
    """
    Persist a batch of validated options records to options_chain table.

    Args:
        records: Validated OptionRecord objects to insert.
        engine: SQLAlchemy Engine for the target database.

    Returns:
        Number of records successfully written.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "write_option_records not yet implemented. " "TODO: Batch INSERT into options_chain table."
    )


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
