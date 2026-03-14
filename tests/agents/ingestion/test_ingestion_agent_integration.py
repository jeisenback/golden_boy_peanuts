"""
Integration tests for the Ingestion Agent.

Uses testcontainers.postgres.PostgresContainer — no mocked DB.
All tests in this module are marked with @pytest.mark.integration and are
excluded from the default `pytest -m "not integration"` run.

Coverage:
  - write_price_records(): round-trip write + query, assert row count and field values
  - write_option_records(): round-trip write + query, assert row count and field values
  - run_ingestion(): mocked feeds, real DB — assert rows written to both tables
  - run_ingestion(): one feed raises — partial records written, ingestion_errors populated
"""

from __future__ import annotations

import os

# Disable testcontainers Reaper (Ryuk) — required on Windows where the Reaper
# container's port mapping is unavailable. Must be set before any testcontainers import.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from collections.abc import Generator
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.agents.ingestion.db import write_option_records, write_price_records
from src.agents.ingestion.ingestion_agent import run_ingestion
from src.agents.ingestion.models import InstrumentType, OptionRecord, RawPriceRecord

# ---------------------------------------------------------------------------
# Patch targets for run_ingestion() feeds
# ---------------------------------------------------------------------------
_PATCH_CRUDE = "src.agents.ingestion.ingestion_agent.fetch_crude_prices"
_PATCH_ETF = "src.agents.ingestion.ingestion_agent.fetch_etf_equity_prices"
_PATCH_OPTIONS = "src.agents.ingestion.ingestion_agent.fetch_options_chain"
_PATCH_ENGINE = "src.agents.ingestion.ingestion_agent.get_engine"

# ---------------------------------------------------------------------------
# Schema DDL — mirrors db/schema.sql (no migrations needed in test containers)
# ---------------------------------------------------------------------------
_DDL = """
CREATE TABLE IF NOT EXISTS market_prices (
    id              BIGSERIAL       PRIMARY KEY,
    instrument      TEXT            NOT NULL,
    instrument_type TEXT            NOT NULL,
    price           NUMERIC(18, 6)  NOT NULL,
    volume          BIGINT,
    source          TEXT            NOT NULL,
    timestamp       TIMESTAMPTZ     NOT NULL
);

CREATE TABLE IF NOT EXISTS options_chain (
    id                  BIGSERIAL       PRIMARY KEY,
    instrument          TEXT            NOT NULL,
    strike              NUMERIC(18, 6)  NOT NULL,
    expiration_date     TIMESTAMPTZ     NOT NULL,
    implied_volatility  NUMERIC(10, 6),
    open_interest       BIGINT,
    volume              BIGINT,
    option_type         TEXT            NOT NULL
                            CHECK (option_type IN ('call', 'put')),
    source              TEXT            NOT NULL,
    timestamp           TIMESTAMPTZ     NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine() -> Generator[Engine, None, None]:
    """Start a PostgresContainer, apply schema, yield engine, stop container."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:15") as pg:
        engine = create_engine(pg.get_connection_url())
        with engine.begin() as conn:
            conn.execute(text(_DDL))
        yield engine


@pytest.fixture(autouse=True)
def _clean_tables(pg_engine):
    """Truncate both tables before each test so tests are isolated."""
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE market_prices, options_chain RESTART IDENTITY"))
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_price(instrument: str = "CL=F", price: float = 75.50) -> RawPriceRecord:
    return RawPriceRecord(
        instrument=instrument,
        instrument_type=InstrumentType.CRUDE_FUTURES,
        price=price,
        volume=123456,
        timestamp=datetime.now(timezone.utc),
        source="test",
    )


def _make_option(instrument: str = "USO", option_type: str = "call") -> OptionRecord:
    return OptionRecord(
        instrument=instrument,
        strike=100.0,
        expiration_date=datetime(2030, 1, 17, tzinfo=timezone.utc),
        implied_volatility=0.25,
        open_interest=500,
        volume=200,
        option_type=option_type,
        timestamp=datetime.now(timezone.utc),
        source="test",
    )


# ---------------------------------------------------------------------------
# write_price_records round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_write_price_records_round_trip(pg_engine) -> None:
    """write_price_records() inserts N rows; query confirms count and key field values."""
    records = [_make_price("CL=F", 75.50), _make_price("BZ=F", 82.30)]

    count = write_price_records(records, pg_engine)

    assert count == 2

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT instrument, price, source FROM market_prices ORDER BY instrument")
        ).fetchall()

    assert len(rows) == 2
    instruments = [r[0] for r in rows]
    assert "BZ=F" in instruments
    assert "CL=F" in instruments
    prices = {r[0]: float(r[1]) for r in rows}
    assert abs(prices["CL=F"] - 75.50) < 1e-4
    assert abs(prices["BZ=F"] - 82.30) < 1e-4
    assert all(r[2] == "test" for r in rows)


@pytest.mark.integration
def test_write_price_records_empty_returns_zero(pg_engine) -> None:
    """write_price_records([]) returns 0 and inserts nothing."""
    count = write_price_records([], pg_engine)

    assert count == 0

    with pg_engine.connect() as conn:
        row_count = conn.execute(text("SELECT COUNT(*) FROM market_prices")).scalar()
    assert row_count == 0


@pytest.mark.integration
def test_write_price_records_null_volume(pg_engine) -> None:
    """volume=None is persisted as NULL (nullable column)."""
    record = RawPriceRecord(
        instrument="USO",
        instrument_type=InstrumentType.ETF,
        price=62.10,
        volume=None,
        timestamp=datetime.now(timezone.utc),
        source="test",
    )
    write_price_records([record], pg_engine)

    with pg_engine.connect() as conn:
        vol = conn.execute(text("SELECT volume FROM market_prices LIMIT 1")).scalar()
    assert vol is None


# ---------------------------------------------------------------------------
# write_option_records round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_write_option_records_round_trip(pg_engine) -> None:
    """write_option_records() inserts N rows; query confirms count and field values."""
    records = [_make_option("USO", "call"), _make_option("USO", "put")]

    count = write_option_records(records, pg_engine)

    assert count == 2

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT instrument, strike, option_type, implied_volatility "
                "FROM options_chain ORDER BY option_type"
            )
        ).fetchall()

    assert len(rows) == 2
    option_types = {r[2] for r in rows}
    assert option_types == {"call", "put"}
    assert all(r[0] == "USO" for r in rows)
    assert all(abs(float(r[1]) - 100.0) < 1e-4 for r in rows)
    assert all(abs(float(r[3]) - 0.25) < 1e-4 for r in rows)


@pytest.mark.integration
def test_write_option_records_null_implied_volatility(pg_engine) -> None:
    """implied_volatility=None is persisted as NULL (nullable column)."""
    record = OptionRecord(
        instrument="XLE",
        strike=55.0,
        expiration_date=datetime(2030, 6, 20, tzinfo=timezone.utc),
        implied_volatility=None,
        open_interest=None,
        volume=None,
        option_type="put",
        timestamp=datetime.now(timezone.utc),
        source="test",
    )
    write_option_records([record], pg_engine)

    with pg_engine.connect() as conn:
        iv = conn.execute(text("SELECT implied_volatility FROM options_chain LIMIT 1")).scalar()
    assert iv is None


# ---------------------------------------------------------------------------
# run_ingestion() integration — mocked feeds, real DB
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_run_ingestion_writes_to_both_tables(pg_engine) -> None:
    """run_ingestion() with mocked feeds writes rows to market_prices and options_chain."""
    crude_records = [_make_price("CL=F"), _make_price("BZ=F")]
    etf_records = [_make_price("USO"), _make_price("XLE")]
    option_records = [_make_option("USO", "call"), _make_option("USO", "put")]

    with (
        patch(_PATCH_CRUDE, return_value=crude_records),
        patch(_PATCH_ETF, return_value=etf_records),
        patch(_PATCH_OPTIONS, return_value=option_records),
        patch(_PATCH_ENGINE, return_value=pg_engine),
    ):
        state = run_ingestion()

    assert state.ingestion_errors == []
    assert len(state.prices) == 4
    assert len(state.options) == 2

    with pg_engine.connect() as conn:
        price_count = conn.execute(text("SELECT COUNT(*) FROM market_prices")).scalar()
        option_count = conn.execute(text("SELECT COUNT(*) FROM options_chain")).scalar()

    assert price_count == 4
    assert option_count == 2


@pytest.mark.integration
def test_run_ingestion_partial_failure_writes_partial_records(pg_engine) -> None:
    """One feed raising writes records from other feeds and populates ingestion_errors."""
    etf_records = [_make_price("USO"), _make_price("XLE")]
    option_records = [_make_option("USO", "call")]

    with (
        patch(_PATCH_CRUDE, side_effect=RuntimeError("API key missing")),
        patch(_PATCH_ETF, return_value=etf_records),
        patch(_PATCH_OPTIONS, return_value=option_records),
        patch(_PATCH_ENGINE, return_value=pg_engine),
    ):
        state = run_ingestion()

    # Crude feed failed → error recorded; ETF and options still written
    assert len(state.ingestion_errors) == 1
    assert "fetch_crude_prices" in state.ingestion_errors[0]
    assert len(state.prices) == 2  # ETF only
    assert len(state.options) == 1

    with pg_engine.connect() as conn:
        price_count = conn.execute(text("SELECT COUNT(*) FROM market_prices")).scalar()
        option_count = conn.execute(text("SELECT COUNT(*) FROM options_chain")).scalar()

    assert price_count == 2
    assert option_count == 1
