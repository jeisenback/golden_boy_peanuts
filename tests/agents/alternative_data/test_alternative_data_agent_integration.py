"""
Integration tests for the Alternative Data Agent (issue #160).

Uses testcontainers.postgres.PostgresContainer — no mocked DB.
All tests in this module are marked with @pytest.mark.integration and are
excluded from the default `pytest -m "not integration"` run.

Coverage:
  - write_insider_trades(): round-trip write + query, assert row count and field values
  - write_shipping_events(): round-trip write + query, assert row count and field values
  - write_narrative_signal(): round-trip write + query, sentiment translation, idempotency
  - run_alternative_data_ingestion(): mocked feeds, real DB — all three tables written
  - run_alternative_data_ingestion(): one feed raises — partial records written,
    alternative_data_errors populated
"""

from __future__ import annotations

import os

# Disable testcontainers Reaper (Ryuk) — required on Windows where the Reaper
# container's port mapping is unavailable. Must be set before any testcontainers import.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from collections.abc import Generator
from datetime import UTC, datetime
import pathlib
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.agents.alternative_data.alternative_data_agent import run_alternative_data_ingestion
from src.agents.alternative_data.db import (
    write_insider_trades,
    write_narrative_signal,
    write_shipping_events,
)
from src.agents.alternative_data.models import (
    EventType,
    InsiderTrade,
    NarrativeSignal,
    Sentiment,
    ShippingEvent,
)

# ---------------------------------------------------------------------------
# Patch targets for run_alternative_data_ingestion() feeds
# ---------------------------------------------------------------------------
_PATCH_EDGAR = "src.agents.alternative_data.alternative_data_agent.fetch_edgar_insider_trades"
_PATCH_QUIVER = "src.agents.alternative_data.alternative_data_agent.fetch_quiver_enrichment"
_PATCH_REDDIT = "src.agents.alternative_data.alternative_data_agent.fetch_reddit_sentiment"
_PATCH_STOCKTWITS = "src.agents.alternative_data.alternative_data_agent.fetch_stocktwits_sentiment"
_PATCH_TANKER = "src.agents.alternative_data.alternative_data_agent.fetch_tanker_flows"
_PATCH_ENGINE = "src.agents.alternative_data.alternative_data_agent.get_engine"

# ---------------------------------------------------------------------------
# Schema path — applies the real db/schema.sql (all Phase 1-3 tables, exact
# CHECK constraints and column types) rather than a hand-duplicated subset.
# ---------------------------------------------------------------------------
_SCHEMA_PATH = pathlib.Path(__file__).parents[3] / "db" / "schema.sql"
_PG_IMAGE: str = "postgres:15"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine() -> Generator[Engine, None, None]:
    """Start a real Postgres container, apply the full schema, yield engine."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(_PG_IMAGE) as pg:
        engine = create_engine(pg.get_connection_url())
        with engine.begin() as conn:
            conn.exec_driver_sql(_SCHEMA_PATH.read_text(encoding="utf-8"))
        yield engine


@pytest.fixture(autouse=True)
def _clean_tables(pg_engine: Engine) -> Generator[None, None, None]:
    """Truncate the three alternative-data tables before each test for isolation."""
    with pg_engine.begin() as conn:
        conn.execute(
            text("TRUNCATE insider_trades, shipping_events, narrative_signals RESTART IDENTITY")
        )
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_insider_trade(
    instrument: str = "XOM",
    trade_type: str = "buy",
    value_usd: float | None = 50_000.0,
) -> InsiderTrade:
    return InsiderTrade(
        instrument=instrument,
        trade_date=datetime.now(tz=UTC),
        trade_type=trade_type,
        shares=1000,
        value_usd=value_usd,
        officer_name="Jane Smith",
        source="edgar",
    )


def _make_shipping_event(
    vessel_id: str = "VESSEL1",
    event_type: EventType = EventType.TRANSIT,
    instrument: str | None = "CL=F",
) -> ShippingEvent:
    return ShippingEvent(
        vessel_id=vessel_id,
        event_type=event_type,
        latitude=26.0,
        longitude=56.5,
        timestamp=datetime.now(tz=UTC),
        source="marinetraffic",
        instrument=instrument,
    )


def _make_narrative_signal(
    instrument: str = "USO",
    platform: str = "reddit",
    score: int = 25,
    mention_count: int = 40,
    sentiment: Sentiment = Sentiment.POSITIVE,
    window_start: datetime | None = None,
) -> NarrativeSignal:
    ws = window_start or datetime.now(tz=UTC)
    return NarrativeSignal(
        instrument=instrument,
        platform=platform,
        score=score,
        mention_count=mention_count,
        sentiment=sentiment,
        window_start=ws,
        window_end=ws,
        source=platform,
    )


# ---------------------------------------------------------------------------
# write_insider_trades round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_write_insider_trades_round_trip(pg_engine: Engine) -> None:
    """write_insider_trades() inserts N rows; query confirms count and field values."""
    records = [
        _make_insider_trade("XOM", "buy", 50_000.0),
        _make_insider_trade("CVX", "sell", 20_000.0),
    ]

    count = write_insider_trades(records, pg_engine)

    assert count == 2

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT instrument, trade_type, value_usd, officer_name, source "
                "FROM insider_trades ORDER BY instrument"
            )
        ).fetchall()

    assert len(rows) == 2
    by_instrument = {r[0]: r for r in rows}
    assert by_instrument["CVX"][1] == "sell"
    assert abs(float(by_instrument["CVX"][2]) - 20_000.0) < 1e-2
    assert by_instrument["XOM"][1] == "buy"
    assert abs(float(by_instrument["XOM"][2]) - 50_000.0) < 1e-2
    assert all(r[3] == "Jane Smith" for r in rows)
    assert all(r[4] == "edgar" for r in rows)


@pytest.mark.integration
def test_write_insider_trades_empty_returns_zero(pg_engine: Engine) -> None:
    """write_insider_trades([]) returns 0 and inserts nothing."""
    count = write_insider_trades([], pg_engine)

    assert count == 0

    with pg_engine.connect() as conn:
        row_count = conn.execute(text("SELECT COUNT(*) FROM insider_trades")).scalar()
    assert row_count == 0


@pytest.mark.integration
def test_write_insider_trades_null_value_usd(pg_engine: Engine) -> None:
    """value_usd=None is persisted as NULL (nullable column)."""
    record = _make_insider_trade("USO", "buy", value_usd=None)
    write_insider_trades([record], pg_engine)

    with pg_engine.connect() as conn:
        value_usd = conn.execute(text("SELECT value_usd FROM insider_trades LIMIT 1")).scalar()
    assert value_usd is None


# ---------------------------------------------------------------------------
# write_shipping_events round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_write_shipping_events_round_trip(pg_engine: Engine) -> None:
    """write_shipping_events() inserts N rows; query confirms count and field values."""
    records = [
        _make_shipping_event("V1", EventType.TRANSIT),
        _make_shipping_event("V2", EventType.ANCHORED),
    ]

    count = write_shipping_events(records, pg_engine)

    assert count == 2

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT vessel_id, event_type, latitude, longitude, instrument "
                "FROM shipping_events ORDER BY vessel_id"
            )
        ).fetchall()

    assert len(rows) == 2
    by_vessel = {r[0]: r for r in rows}
    assert by_vessel["V1"][1] == "transit"
    assert by_vessel["V2"][1] == "anchored"
    assert all(abs(float(r[2]) - 26.0) < 1e-4 for r in rows)
    assert all(abs(float(r[3]) - 56.5) < 1e-4 for r in rows)
    assert all(r[4] == "CL=F" for r in rows)


@pytest.mark.integration
def test_write_shipping_events_null_instrument(pg_engine: Engine) -> None:
    """instrument=None is persisted as NULL (vessel not tied to one instrument)."""
    record = _make_shipping_event("V3", EventType.DELAYED, instrument=None)
    write_shipping_events([record], pg_engine)

    with pg_engine.connect() as conn:
        instrument = conn.execute(text("SELECT instrument FROM shipping_events LIMIT 1")).scalar()
    assert instrument is None


# ---------------------------------------------------------------------------
# write_narrative_signal round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_write_narrative_signal_round_trip_translates_sentiment(pg_engine: Engine) -> None:
    """write_narrative_signal() inserts a row; sentiment is translated to the DB's
    bullish/bearish/neutral vocabulary via _SENTIMENT_DB_MAP (Sentiment.POSITIVE -> 'bullish')."""
    record = _make_narrative_signal("USO", "reddit", score=30, sentiment=Sentiment.POSITIVE)

    inserted = write_narrative_signal(record, pg_engine)

    assert inserted == 1

    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT instrument, platform, score, mention_count, sentiment "
                "FROM narrative_signals LIMIT 1"
            )
        ).fetchone()

    assert row is not None
    assert row[0] == "USO"
    assert row[1] == "reddit"
    assert int(row[2]) == 30
    assert row[3] == 40
    assert row[4] == "bullish"  # Sentiment.POSITIVE -> 'bullish' via _SENTIMENT_DB_MAP


@pytest.mark.integration
def test_write_narrative_signal_negative_sentiment_translates_to_bearish(pg_engine: Engine) -> None:
    """Sentiment.NEGATIVE -> 'bearish' via _SENTIMENT_DB_MAP."""
    record = _make_narrative_signal("XLE", "stocktwits", sentiment=Sentiment.NEGATIVE)
    write_narrative_signal(record, pg_engine)

    with pg_engine.connect() as conn:
        sentiment = conn.execute(text("SELECT sentiment FROM narrative_signals LIMIT 1")).scalar()
    assert sentiment == "bearish"


@pytest.mark.integration
def test_write_narrative_signal_duplicate_window_is_idempotent(pg_engine: Engine) -> None:
    """Re-writing the same (instrument, platform, window_start) is a no-op —
    ON CONFLICT DO NOTHING — matching db.py's documented idempotent re-ingestion contract."""
    window_start = datetime.now(tz=UTC)
    first = _make_narrative_signal("USO", "reddit", score=10, window_start=window_start)
    # score must still fit narrative_signals.score NUMERIC(6,4) (max magnitude ~99.9999):
    # Postgres type-checks the VALUES clause while building the candidate row before
    # it evaluates ON CONFLICT, so an out-of-range literal would raise regardless of
    # whether the row is ultimately skipped.
    second = _make_narrative_signal("USO", "reddit", score=99, window_start=window_start)

    first_result = write_narrative_signal(first, pg_engine)
    second_result = write_narrative_signal(second, pg_engine)

    assert first_result == 1
    assert second_result == 0  # skipped — conflict on (instrument, platform, window_start)

    with pg_engine.connect() as conn:
        row_count = conn.execute(text("SELECT COUNT(*) FROM narrative_signals")).scalar()
        score = conn.execute(text("SELECT score FROM narrative_signals LIMIT 1")).scalar()

    assert row_count == 1
    assert score is not None
    assert int(score) == 10  # original row untouched, not overwritten by the second write


# ---------------------------------------------------------------------------
# run_alternative_data_ingestion() integration — mocked feeds, real DB
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_run_alternative_data_ingestion_writes_all_three_tables(pg_engine: Engine) -> None:
    """run_alternative_data_ingestion() with mocked feeds writes rows to all three tables."""
    edgar_trades = [_make_insider_trade("XOM", "buy")]
    quiver_trades = [_make_insider_trade("CVX", "sell")]
    reddit_signals = [_make_narrative_signal("USO", "reddit", window_start=datetime.now(tz=UTC))]
    stocktwits_signals = [
        _make_narrative_signal("XLE", "stocktwits", window_start=datetime.now(tz=UTC))
    ]
    shipping_events = [_make_shipping_event("V1", EventType.TRANSIT)]

    with (
        patch(_PATCH_EDGAR, return_value=edgar_trades),
        patch(_PATCH_QUIVER, return_value=quiver_trades),
        patch(_PATCH_REDDIT, return_value=reddit_signals),
        patch(_PATCH_STOCKTWITS, return_value=stocktwits_signals),
        patch(_PATCH_TANKER, return_value=shipping_events),
        patch(_PATCH_ENGINE, return_value=pg_engine),
    ):
        state = run_alternative_data_ingestion()

    assert state.alternative_data_errors == []
    assert len(state.insider_trades) == 2
    assert len(state.narrative_signals) == 2
    assert len(state.shipping_events) == 1

    with pg_engine.connect() as conn:
        insider_count = conn.execute(text("SELECT COUNT(*) FROM insider_trades")).scalar()
        narrative_count = conn.execute(text("SELECT COUNT(*) FROM narrative_signals")).scalar()
        shipping_count = conn.execute(text("SELECT COUNT(*) FROM shipping_events")).scalar()

    assert insider_count == 2
    assert narrative_count == 2
    assert shipping_count == 1


@pytest.mark.integration
def test_run_alternative_data_ingestion_partial_failure_writes_partial_records(
    pg_engine: Engine,
) -> None:
    """One feed raising writes records from the other feeds and populates
    alternative_data_errors — matching run_ingestion()'s established pattern."""
    quiver_trades = [_make_insider_trade("CVX", "sell")]
    reddit_signals = [_make_narrative_signal("USO", "reddit", window_start=datetime.now(tz=UTC))]
    stocktwits_signals = [
        _make_narrative_signal("XLE", "stocktwits", window_start=datetime.now(tz=UTC))
    ]
    shipping_events = [_make_shipping_event("V1", EventType.TRANSIT)]

    with (
        patch(_PATCH_EDGAR, side_effect=RuntimeError("EDGAR EFTS unavailable")),
        patch(_PATCH_QUIVER, return_value=quiver_trades),
        patch(_PATCH_REDDIT, return_value=reddit_signals),
        patch(_PATCH_STOCKTWITS, return_value=stocktwits_signals),
        patch(_PATCH_TANKER, return_value=shipping_events),
        patch(_PATCH_ENGINE, return_value=pg_engine),
    ):
        state = run_alternative_data_ingestion()

    # EDGAR feed failed -> error recorded; other feeds still fetched and written
    assert len(state.alternative_data_errors) == 1
    assert "fetch_edgar_insider_trades" in state.alternative_data_errors[0]
    assert len(state.insider_trades) == 1  # Quiver only
    assert len(state.narrative_signals) == 2
    assert len(state.shipping_events) == 1

    with pg_engine.connect() as conn:
        insider_count = conn.execute(text("SELECT COUNT(*) FROM insider_trades")).scalar()
        narrative_count = conn.execute(text("SELECT COUNT(*) FROM narrative_signals")).scalar()
        shipping_count = conn.execute(text("SELECT COUNT(*) FROM shipping_events")).scalar()

    assert insider_count == 1
    assert narrative_count == 2
    assert shipping_count == 1
