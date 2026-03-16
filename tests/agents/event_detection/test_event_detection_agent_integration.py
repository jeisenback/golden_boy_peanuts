"""
Integration tests for the Event Detection Agent.

Uses testcontainers.postgres.PostgresContainer — no mocked DB.
All tests are marked with @pytest.mark.integration and excluded from the
default `pytest -m "not integration"` run.

Coverage:
  - write_detected_events / read_recent_events: round-trip with JSONB fields
  - Duplicate event_id: ON CONFLICT DO NOTHING — exactly one row
  - run_event_detection: mocked feeds + real DB → events classified, written, returned
  - run_event_detection: one feed raises — partial results, errors logged, no propagation
  - write_eia_records: round-trip + idempotent re-insert (same period → no duplicates)
"""

from __future__ import annotations

import os

# Disable testcontainers Reaper (Ryuk) — required on Windows and some CI environments.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.agents.event_detection.db import (
    read_recent_events,
    write_detected_events,
    write_eia_records,
)
from src.agents.event_detection.event_detection_agent import run_event_detection
from src.agents.event_detection.models import (
    DetectedEvent,
    EIAInventoryRecord,
    EventIntensity,
    EventType,
)

# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------
_PATCH_FETCH_NEWS = "src.agents.event_detection.event_detection_agent.fetch_news_events"
_PATCH_FETCH_GDELT = "src.agents.event_detection.event_detection_agent.fetch_gdelt_events"
_PATCH_FETCH_EIA = "src.agents.event_detection.event_detection_agent.fetch_eia_data"
_PATCH_CLASSIFY = "src.agents.event_detection.event_detection_agent.classify_event"
_PATCH_GET_ENGINE = "src.agents.event_detection.event_detection_agent.get_engine"

# ---------------------------------------------------------------------------
# DDL — mirrors detected_events and eia_inventory from db/schema.sql
# ---------------------------------------------------------------------------
_DDL = """
CREATE TABLE IF NOT EXISTS detected_events (
    id                      BIGSERIAL       PRIMARY KEY,
    event_id                TEXT            NOT NULL,
    event_type              TEXT            NOT NULL,
    description             TEXT            NOT NULL,
    source                  TEXT            NOT NULL,
    confidence_score        NUMERIC(5, 4)   NOT NULL,
    intensity               TEXT            NOT NULL,
    detected_at             TIMESTAMPTZ     NOT NULL,
    affected_instruments    JSONB,
    raw_headline            TEXT,
    CONSTRAINT uq_detected_events_event_id UNIQUE (event_id)
);

CREATE TABLE IF NOT EXISTS eia_inventory (
    id                          BIGSERIAL       PRIMARY KEY,
    period                      TEXT            NOT NULL,
    crude_stocks_mb             NUMERIC(12, 3),
    refinery_utilization_pct    NUMERIC(6, 3),
    source                      TEXT            NOT NULL DEFAULT 'eia',
    fetched_at                  TIMESTAMPTZ     NOT NULL,
    CONSTRAINT uq_eia_inventory_period UNIQUE (period)
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
def _clean_tables(pg_engine: Engine) -> Generator[None, None, None]:
    """Truncate both tables before each test for isolation."""
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE detected_events, eia_inventory RESTART IDENTITY"))
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_id: str = "abc123",
    event_type: EventType = EventType.SUPPLY_DISRUPTION,
    description: str = "Test supply disruption event",
    source: str = "newsapi",
    confidence_score: float = 0.85,
    intensity: EventIntensity = EventIntensity.HIGH,
    affected_instruments: list[str] | None = None,
    raw_headline: str | None = "Oil supply disrupted in Gulf",
) -> DetectedEvent:
    return DetectedEvent(
        event_id=event_id,
        event_type=event_type,
        description=description,
        source=source,
        confidence_score=confidence_score,
        intensity=intensity,
        detected_at=datetime.now(tz=UTC),
        affected_instruments=affected_instruments or ["CL=F", "USO"],
        raw_headline=raw_headline,
    )


def _make_eia_record(
    period: str = "2026-10",
    crude_stocks_mb: float | None = 430.5,
    refinery_utilization_pct: float | None = 91.2,
) -> EIAInventoryRecord:
    return EIAInventoryRecord(
        period=period,
        crude_stocks_mb=crude_stocks_mb,
        refinery_utilization_pct=refinery_utilization_pct,
        fetched_at=datetime.now(tz=UTC),
    )


# ---------------------------------------------------------------------------
# Tests — write_detected_events / read_recent_events round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_write_read_round_trip(pg_engine: Engine) -> None:
    """Write a DetectedEvent and read it back; all fields including JSONB persist."""
    event = _make_event(
        event_id="roundtrip-001",
        affected_instruments=["CL=F", "BZ=F", "USO"],
    )
    count = write_detected_events([event], pg_engine)
    assert count == 1

    events = read_recent_events(pg_engine, limit=10)
    assert len(events) == 1

    e = events[0]
    assert e.event_id == "roundtrip-001"
    assert e.event_type == EventType.SUPPLY_DISRUPTION
    assert e.description == "Test supply disruption event"
    assert e.source == "newsapi"
    assert float(e.confidence_score) == pytest.approx(0.85, abs=1e-4)
    assert e.intensity == EventIntensity.HIGH
    assert e.affected_instruments == ["CL=F", "BZ=F", "USO"]
    assert e.raw_headline == "Oil supply disrupted in Gulf"


@pytest.mark.integration
def test_duplicate_event_id_ignored(pg_engine: Engine) -> None:
    """ON CONFLICT (event_id) DO NOTHING — second insert silently skipped."""
    event = _make_event(event_id="dup-001")
    write_detected_events([event], pg_engine)
    write_detected_events([event], pg_engine)

    events = read_recent_events(pg_engine, limit=10)
    assert len(events) == 1


@pytest.mark.integration
def test_multiple_events_persisted(pg_engine: Engine) -> None:
    """Multiple distinct events are all persisted."""
    events = [
        _make_event(event_id="multi-001", description="Event 1"),
        _make_event(event_id="multi-002", description="Event 2"),
        _make_event(event_id="multi-003", description="Event 3"),
    ]
    count = write_detected_events(events, pg_engine)
    assert count == 3

    read_back = read_recent_events(pg_engine, limit=10)
    assert len(read_back) == 3


# ---------------------------------------------------------------------------
# Tests — write_eia_records round-trip and idempotency
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_eia_write_read_round_trip(pg_engine: Engine) -> None:
    """Write EIA records and verify they persist correctly."""
    records = [
        _make_eia_record(period="2026-10", crude_stocks_mb=430.5, refinery_utilization_pct=91.2),
        _make_eia_record(period="2026-11", crude_stocks_mb=425.0, refinery_utilization_pct=89.5),
    ]
    count = write_eia_records(records, pg_engine)
    assert count == 2

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT period, crude_stocks_mb, refinery_utilization_pct"
                " FROM eia_inventory ORDER BY period"
            )
        ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "2026-10"
    assert float(rows[0][1]) == pytest.approx(430.5, abs=0.01)
    assert float(rows[0][2]) == pytest.approx(91.2, abs=0.01)


@pytest.mark.integration
def test_eia_duplicate_period_ignored(pg_engine: Engine) -> None:
    """ON CONFLICT (period) DO NOTHING — re-insert same period produces no duplicate."""
    record = _make_eia_record(period="2026-10")
    write_eia_records([record], pg_engine)
    write_eia_records([record], pg_engine)

    with pg_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM eia_inventory")).scalar()
    assert count == 1


# ---------------------------------------------------------------------------
# Tests — run_event_detection with mocked feeds + real DB
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_run_event_detection_full_cycle(pg_engine: Engine) -> None:
    """Mocked feeds + real DB: events classified, written, and returned."""
    event = _make_event(event_id="cycle-001")

    with (
        patch(_PATCH_FETCH_NEWS, return_value=[{"title": "Oil disruption", "url": "http://example.com/1"}]),
        patch(_PATCH_FETCH_GDELT, return_value=[]),
        patch(_PATCH_FETCH_EIA, return_value=[]),
        patch(_PATCH_CLASSIFY, return_value=event),
        patch(_PATCH_GET_ENGINE, return_value=pg_engine),
    ):
        result = run_event_detection()

    assert len(result) == 1
    assert result[0].event_id == "cycle-001"

    # Verify DB persistence
    db_events = read_recent_events(pg_engine, limit=10)
    assert len(db_events) == 1
    assert db_events[0].event_id == "cycle-001"


@pytest.mark.integration
def test_run_event_detection_partial_failure(pg_engine: Engine) -> None:
    """One fetch raises — other feeds succeed, errors don't propagate."""
    event = _make_event(event_id="partial-001")

    with (
        patch(_PATCH_FETCH_NEWS, side_effect=RuntimeError("NewsAPI down")),
        patch(_PATCH_FETCH_GDELT, return_value=[{"title": "GDELT article", "url": "http://gdelt.example.com/1"}]),
        patch(_PATCH_FETCH_EIA, return_value=[]),
        patch(_PATCH_CLASSIFY, return_value=event),
        patch(_PATCH_GET_ENGINE, return_value=pg_engine),
    ):
        result = run_event_detection()

    # GDELT article still classified and returned
    assert len(result) == 1
    assert result[0].event_id == "partial-001"

    # Verify DB persistence for successful feed
    db_events = read_recent_events(pg_engine, limit=10)
    assert len(db_events) == 1
