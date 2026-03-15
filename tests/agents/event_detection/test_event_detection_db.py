"""
Unit tests for Event Detection Agent DB functions (write_detected_events,
read_recent_events, write_eia_records).

Uses MagicMock to simulate the SQLAlchemy engine/connection without a real DB.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.agents.event_detection.db import (
    read_recent_events,
    write_detected_events,
    write_eia_records,
)
from src.agents.event_detection.models import (
    DetectedEvent,
    EIAInventoryRecord,
    EventIntensity,
    EventType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 15, 20, 0, 0, tzinfo=UTC)


def _make_event(
    event_id: str = "abc123",
    event_type: EventType = EventType.SUPPLY_DISRUPTION,
    intensity: EventIntensity = EventIntensity.HIGH,
    confidence_score: float = 0.9,
    affected_instruments: list[str] | None = None,
) -> DetectedEvent:
    return DetectedEvent(
        event_id=event_id,
        event_type=event_type,
        description="OPEC cuts output by 1 mb/d",
        source="newsapi",
        confidence_score=confidence_score,
        intensity=intensity,
        detected_at=_NOW,
        affected_instruments=affected_instruments or ["USO", "XLE"],
        raw_headline="OPEC agrees to cut",
    )


def _make_eia_record(period: str = "2024-10") -> EIAInventoryRecord:
    return EIAInventoryRecord(
        period=period,
        crude_stocks_mb=430.5,
        refinery_utilization_pct=91.2,
        source="eia",
        fetched_at=_NOW,
    )


def _make_engine() -> MagicMock:
    """Return a mock engine whose begin() and connect() context managers work."""
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


# ---------------------------------------------------------------------------
# write_detected_events
# ---------------------------------------------------------------------------


class TestWriteDetectedEvents:
    def test_empty_list_returns_zero(self) -> None:
        """Empty input is a no-op; engine is never touched."""
        engine, _ = _make_engine()
        result = write_detected_events([], engine)
        assert result == 0
        engine.begin.assert_not_called()

    def test_single_event_executes_insert(self) -> None:
        """One event produces one conn.execute() call with correct row data."""
        engine, conn = _make_engine()
        event = _make_event()
        result = write_detected_events([event], engine)
        assert result == 1
        conn.execute.assert_called_once()
        _, rows = conn.execute.call_args.args
        assert len(rows) == 1
        assert rows[0]["event_id"] == "abc123"
        assert rows[0]["event_type"] == "supply_disruption"
        assert rows[0]["intensity"] == "high"
        assert rows[0]["confidence_score"] == 0.9

    def test_multiple_events_all_included(self) -> None:
        """All events in a batch are included in the single execute call."""
        engine, conn = _make_engine()
        events = [_make_event(event_id=f"id{i}") for i in range(5)]
        result = write_detected_events(events, engine)
        assert result == 5
        _, rows = conn.execute.call_args.args
        assert len(rows) == 5

    def test_affected_instruments_serialized_as_json(self) -> None:
        """affected_instruments list is JSON-serialized for the JSONB column."""
        import json

        engine, conn = _make_engine()
        event = _make_event(affected_instruments=["USO", "XLE", "XOM"])
        write_detected_events([event], engine)
        _, rows = conn.execute.call_args.args
        assert json.loads(rows[0]["affected_instruments"]) == ["USO", "XLE", "XOM"]

    def test_db_exception_propagates(self) -> None:
        """SQLAlchemy errors are re-raised after logging."""
        engine = MagicMock()
        engine.begin.return_value.__enter__ = MagicMock(side_effect=RuntimeError("db down"))
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        with pytest.raises(RuntimeError, match="db down"):
            write_detected_events([_make_event()], engine)


# ---------------------------------------------------------------------------
# read_recent_events
# ---------------------------------------------------------------------------


class TestReadRecentEvents:
    def _make_row(self, event_id: str = "abc123") -> MagicMock:
        row = MagicMock()
        row.__getitem__ = lambda self, key: {
            "event_id": event_id,
            "event_type": "supply_disruption",
            "description": "Test event",
            "source": "newsapi",
            "confidence_score": 0.85,
            "intensity": "high",
            "detected_at": _NOW,
            "affected_instruments": ["USO"],
            "raw_headline": "Oil supply cut",
        }[key]
        return row

    def test_returns_detected_event_list(self) -> None:
        """read_recent_events maps DB rows to DetectedEvent objects."""
        engine, conn = _make_engine()
        conn.execute.return_value.mappings.return_value.all.return_value = [
            self._make_row("ev1"),
            self._make_row("ev2"),
        ]
        result = read_recent_events(engine)
        assert len(result) == 2
        assert all(isinstance(e, DetectedEvent) for e in result)
        assert result[0].event_id == "ev1"

    def test_empty_result_returns_empty_list(self) -> None:
        engine, conn = _make_engine()
        conn.execute.return_value.mappings.return_value.all.return_value = []
        result = read_recent_events(engine)
        assert result == []

    def test_limit_passed_to_query(self) -> None:
        """limit parameter is forwarded to the SQL query."""
        engine, conn = _make_engine()
        conn.execute.return_value.mappings.return_value.all.return_value = []
        read_recent_events(engine, limit=5)
        _, params = conn.execute.call_args.args
        assert params["limit"] == 5

    def test_db_exception_propagates(self) -> None:
        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(side_effect=RuntimeError("timeout"))
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        with pytest.raises(RuntimeError, match="timeout"):
            read_recent_events(engine)


# ---------------------------------------------------------------------------
# write_eia_records
# ---------------------------------------------------------------------------


class TestWriteEiaRecords:
    def test_empty_list_returns_zero(self) -> None:
        engine, _ = _make_engine()
        result = write_eia_records([], engine)
        assert result == 0
        engine.begin.assert_not_called()

    def test_single_record_executes_insert(self) -> None:
        engine, conn = _make_engine()
        record = _make_eia_record("2024-10")
        result = write_eia_records([record], engine)
        assert result == 1
        conn.execute.assert_called_once()
        _, rows = conn.execute.call_args.args
        assert rows[0]["period"] == "2024-10"
        assert rows[0]["crude_stocks_mb"] == 430.5
        assert rows[0]["refinery_utilization_pct"] == 91.2
        assert rows[0]["source"] == "eia"

    def test_multiple_records_batch_inserted(self) -> None:
        engine, conn = _make_engine()
        records = [_make_eia_record(f"2024-{i:02d}") for i in range(1, 5)]
        result = write_eia_records(records, engine)
        assert result == 4
        _, rows = conn.execute.call_args.args
        assert len(rows) == 4

    def test_none_fields_passed_through(self) -> None:
        """Records with None crude_stocks_mb / refinery_utilization_pct are accepted."""
        engine, conn = _make_engine()
        record = EIAInventoryRecord(period="2024-01", fetched_at=_NOW)
        write_eia_records([record], engine)
        _, rows = conn.execute.call_args.args
        assert rows[0]["crude_stocks_mb"] is None
        assert rows[0]["refinery_utilization_pct"] is None

    def test_db_exception_propagates(self) -> None:
        engine = MagicMock()
        engine.begin.return_value.__enter__ = MagicMock(side_effect=RuntimeError("db error"))
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        with pytest.raises(RuntimeError, match="db error"):
            write_eia_records([_make_eia_record()], engine)
