"""
Unit tests for strategy_evaluation db.py — write_strategy_outcome,
fetch_pending_outcomes, and supporting queries.

Uses SQLite in-memory for write/upsert tests. fetch_pending_outcomes
uses PostgreSQL-specific interval syntax, so those tests mock the
connection layer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.agents.strategy_evaluation.db import (
    fetch_pending_outcomes,
    write_strategy_outcome,
)
from src.agents.strategy_evaluation.models import StrategyOutcome

# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

_CANDIDATES_DDL = """\
CREATE TABLE IF NOT EXISTS strategy_candidates (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument    TEXT    NOT NULL,
    structure     TEXT    NOT NULL,
    expiration    INTEGER NOT NULL,
    edge_score    REAL    NOT NULL,
    signals       TEXT    NOT NULL,
    generated_at  TEXT    NOT NULL
)"""

_OUTCOMES_DDL = """\
CREATE TABLE IF NOT EXISTS strategy_outcomes (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id          INTEGER NOT NULL UNIQUE REFERENCES strategy_candidates(id),
    instrument            TEXT    NOT NULL,
    structure             TEXT    NOT NULL,
    generated_at          TEXT    NOT NULL,
    expiration_date       TEXT    NOT NULL,
    price_at_generation   REAL    NOT NULL,
    price_at_expiration   REAL,
    pct_move              REAL,
    recorded_at           TEXT    NOT NULL DEFAULT (datetime('now'))
)"""

_NOW = datetime.now(tz=UTC).replace(microsecond=0)


@pytest.fixture()
def sqlite_engine() -> Engine:
    """In-memory SQLite engine with both tables created."""
    from sqlalchemy import event as sa_event

    engine = create_engine("sqlite:///:memory:")

    @sa_event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _connection_record):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    with engine.begin() as conn:
        conn.execute(text(_CANDIDATES_DDL))
        conn.execute(text(_OUTCOMES_DDL))
    return engine


def _seed_candidate(engine, *, instrument: str = "USO", cid: int | None = None) -> int:
    """Insert a strategy_candidates row and return its id."""
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "INSERT INTO strategy_candidates "
                "(instrument, structure, expiration, edge_score, signals, generated_at) "
                "VALUES (:inst, :struct, :exp, :edge, :sig, :gen)"
            ),
            {
                "inst": instrument,
                "struct": "long_straddle",
                "exp": 30,
                "edge": 0.75,
                "sig": "{}",
                "gen": _NOW.isoformat(),
            },
        )
        return result.lastrowid  # type: ignore[return-value]


def _make_outcome(candidate_id: int, **overrides) -> StrategyOutcome:
    """Build a StrategyOutcome with sensible defaults."""
    defaults = {
        "candidate_id": candidate_id,
        "instrument": "USO",
        "structure": "long_straddle",
        "generated_at": _NOW,
        "expiration_date": _NOW + timedelta(days=30),
        "price_at_generation": 78.50,
        "price_at_expiration": None,
        "pct_move": None,
        "recorded_at": _NOW,
    }
    defaults.update(overrides)
    return StrategyOutcome(**defaults)


# ---------------------------------------------------------------------------
# write_strategy_outcome tests
# ---------------------------------------------------------------------------


class TestWriteStrategyOutcome:
    """Tests for write_strategy_outcome()."""

    def test_write_inserts_new_outcome(self, sqlite_engine) -> None:
        """A new outcome is inserted and returns 1."""
        cid = _seed_candidate(sqlite_engine)
        outcome = _make_outcome(cid, price_at_expiration=82.0, pct_move=0.0446)

        result = write_strategy_outcome(outcome, sqlite_engine)

        assert result == 1
        with sqlite_engine.connect() as conn:
            row = conn.execute(
                text("SELECT candidate_id, price_at_expiration, pct_move FROM strategy_outcomes")
            ).fetchone()
        assert row is not None
        assert row[0] == cid
        assert abs(row[1] - 82.0) < 1e-6
        assert abs(row[2] - 0.0446) < 1e-6

    def test_write_upsert_updates_existing(self, sqlite_engine) -> None:
        """Re-inserting with same candidate_id updates price/move fields."""
        cid = _seed_candidate(sqlite_engine)
        first = _make_outcome(cid, price_at_expiration=None, pct_move=None)
        write_strategy_outcome(first, sqlite_engine)

        updated = _make_outcome(
            cid,
            price_at_expiration=85.0,
            pct_move=0.0828,
            recorded_at=_NOW + timedelta(hours=1),
        )
        result = write_strategy_outcome(updated, sqlite_engine)

        assert result == 1
        with sqlite_engine.connect() as conn:
            rows = conn.execute(
                text("SELECT candidate_id, price_at_expiration, pct_move FROM strategy_outcomes")
            ).fetchall()
        assert len(rows) == 1
        assert abs(rows[0][1] - 85.0) < 1e-6
        assert abs(rows[0][2] - 0.0828) < 1e-6

    def test_write_nullable_fields(self, sqlite_engine) -> None:
        """Outcome with NULL price_at_expiration and pct_move persists."""
        cid = _seed_candidate(sqlite_engine)
        outcome = _make_outcome(cid, price_at_expiration=None, pct_move=None)

        write_strategy_outcome(outcome, sqlite_engine)

        with sqlite_engine.connect() as conn:
            row = conn.execute(
                text("SELECT price_at_expiration, pct_move FROM strategy_outcomes")
            ).fetchone()
        assert row[0] is None
        assert row[1] is None

    def test_write_propagates_db_error(self, sqlite_engine) -> None:
        """Invalid candidate_id triggers FK violation and raises."""
        from sqlalchemy.exc import IntegrityError

        outcome = _make_outcome(99999)
        with pytest.raises(IntegrityError):
            write_strategy_outcome(outcome, sqlite_engine)

    def test_write_zero_pct_move(self, sqlite_engine) -> None:
        """A zero pct_move is stored as 0.0, not NULL."""
        cid = _seed_candidate(sqlite_engine)
        outcome = _make_outcome(cid, price_at_expiration=78.50, pct_move=0.0)

        write_strategy_outcome(outcome, sqlite_engine)

        with sqlite_engine.connect() as conn:
            row = conn.execute(text("SELECT pct_move FROM strategy_outcomes")).fetchone()
        assert row[0] == 0.0


# ---------------------------------------------------------------------------
# fetch_pending_outcomes tests (mocked — PostgreSQL-specific SQL)
# ---------------------------------------------------------------------------


class TestFetchPendingOutcomes:
    """Tests for fetch_pending_outcomes()."""

    def test_returns_pending_candidates(self) -> None:
        """Rows from the query are mapped to dicts with correct keys."""
        fake_row = (1, "USO", "long_straddle", 30, 0.75, _NOW)
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [fake_row]

        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = fetch_pending_outcomes(mock_engine)

        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["instrument"] == "USO"
        assert result[0]["structure"] == "long_straddle"
        assert result[0]["expiration"] == 30
        assert result[0]["edge_score"] == 0.75
        assert result[0]["generated_at"] == _NOW

    def test_returns_empty_when_no_pending(self) -> None:
        """Empty result set returns empty list."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = fetch_pending_outcomes(mock_engine)

        assert result == []

    def test_edge_score_cast_to_float(self) -> None:
        """edge_score is explicitly cast to float in the output."""
        from decimal import Decimal

        fake_row = (5, "XLE", "call_spread", 14, Decimal("0.9200"), _NOW)
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [fake_row]

        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = fetch_pending_outcomes(mock_engine)

        assert isinstance(result[0]["edge_score"], float)
        assert abs(result[0]["edge_score"] - 0.92) < 1e-6
