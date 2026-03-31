"""
Integration test — backtest_candidates and backtest_outcomes tables.

Verifies (against a real Postgres container via testcontainers):
  1. Both tables exist after the migration script is applied.
  2. write_backtest_candidate() inserts a row and returns a valid UUID.
  3. record_outcome() inserts a linked row with profitable=None (audit row).
  4. record_outcome() inserts a row with profitable=True (resolved outcome).
  5. The FK constraint between backtest_outcomes.candidate_id and
     backtest_candidates.id is enforced (referential integrity).

Design notes:
  - Uses db/migrations/add_backtest_tables.sql, NOT the full schema.sql, to
    confirm the migration works standalone (pgcrypto + table + index creation).
  - profitable=None is explicitly tested — it is a valid state per the design
    doc (yfinance returned no data; row still inserted for audit).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
import pathlib
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from testcontainers.postgres import PostgresContainer

from src.backtest.backtest import record_outcome, write_backtest_candidate
from src.backtest.models import BacktestCandidate, BacktestOutcome

# Run integration tests only in CI unless the caller explicitly opts in.
if not os.environ.get("CI"):
    pytest.skip(
        "Integration tests run in CI only. Set CI=1 to run locally.",
        allow_module_level=True,
    )

_MIGRATION_PATH = (
    pathlib.Path(__file__).parents[2] / "db" / "migrations" / "add_backtest_tables.sql"
)

# ---------------------------------------------------------------------------
# Shared timestamps
# ---------------------------------------------------------------------------
_NOW = datetime.now(tz=UTC).replace(microsecond=0)
_SNAPSHOT = _NOW - timedelta(days=30)
_EXPIRATION = _NOW - timedelta(days=7)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_migration(db_url: str) -> None:
    """Apply the backtest migration against a fresh Postgres container."""
    engine = create_engine(db_url)
    sql = _MIGRATION_PATH.read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)


def _make_candidate(instrument: str = "USO") -> BacktestCandidate:
    return BacktestCandidate(
        instrument=instrument,
        structure="long_straddle",
        snapshot_time=_SNAPSHOT,
        edge_score=0.72,
        signals={"volatility_gap": 0.12, "sector_dispersion": 0.08},
        generated_at=_NOW,
    )


def _make_outcome(
    candidate_id: uuid.UUID,
    profitable: bool | None = None,
) -> BacktestOutcome:
    return BacktestOutcome(
        candidate_id=candidate_id,
        structure="long_straddle",
        expiration=_EXPIRATION,
        underlying_close=82.45,
        profitable=profitable,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_migration_creates_both_tables() -> None:
    """Both tables must exist after the migration is applied."""
    with PostgresContainer("postgres:15-alpine") as pg:
        db_url = pg.get_connection_url()
        _apply_migration(db_url)

        engine = create_engine(db_url)
        with engine.connect() as conn:
            tables = (
                conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables"
                        " WHERE table_schema = 'public'"
                        " ORDER BY table_name"
                    )
                )
                .scalars()
                .all()
            )

        assert "backtest_candidates" in tables, "backtest_candidates table missing"
        assert "backtest_outcomes" in tables, "backtest_outcomes table missing"


@pytest.mark.integration
def test_write_backtest_candidate_returns_uuid() -> None:
    """write_backtest_candidate() inserts a row and returns the DB-assigned UUID."""
    with PostgresContainer("postgres:15-alpine") as pg:
        db_url = pg.get_connection_url()
        _apply_migration(db_url)

        engine = create_engine(db_url)
        os.environ["DATABASE_URL"] = db_url

        candidate = _make_candidate("USO")
        assigned_id = write_backtest_candidate(candidate, engine)

        assert isinstance(assigned_id, uuid.UUID), "Expected UUID return type"

        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, instrument, edge_score FROM backtest_candidates")
            ).fetchall()

        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
        assert str(rows[0][0]) == str(assigned_id)
        assert rows[0][1] == "USO"
        assert float(rows[0][2]) == pytest.approx(0.72, abs=1e-4)


@pytest.mark.integration
def test_record_outcome_null_profitable() -> None:
    """
    record_outcome() with profitable=None — audit row for yfinance data gap.
    Row must be inserted with profitable IS NULL, not skipped.
    """
    with PostgresContainer("postgres:15-alpine") as pg:
        db_url = pg.get_connection_url()
        _apply_migration(db_url)

        engine = create_engine(db_url)
        os.environ["DATABASE_URL"] = db_url

        candidate_id = write_backtest_candidate(_make_candidate("XOM"), engine)
        outcome_id = record_outcome(_make_outcome(candidate_id, profitable=None), engine)

        assert isinstance(outcome_id, uuid.UUID)

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT profitable, underlying_close, candidate_id"
                    " FROM backtest_outcomes WHERE id = :id"
                ),
                {"id": str(outcome_id)},
            ).fetchone()

        assert row is not None
        assert row[0] is None, "profitable should be NULL for yfinance data gap"
        assert float(row[1]) == pytest.approx(82.45, abs=1e-4)
        assert str(row[2]) == str(candidate_id)


@pytest.mark.integration
def test_record_outcome_profitable_true() -> None:
    """record_outcome() with profitable=True — resolved long_straddle outcome."""
    with PostgresContainer("postgres:15-alpine") as pg:
        db_url = pg.get_connection_url()
        _apply_migration(db_url)

        engine = create_engine(db_url)
        os.environ["DATABASE_URL"] = db_url

        candidate_id = write_backtest_candidate(_make_candidate("CVX"), engine)
        outcome_id = record_outcome(_make_outcome(candidate_id, profitable=True), engine)

        with engine.connect() as conn:
            profitable = conn.execute(
                text("SELECT profitable FROM backtest_outcomes WHERE id = :id"),
                {"id": str(outcome_id)},
            ).scalar()

        assert profitable is True


@pytest.mark.integration
def test_fk_constraint_rejects_unknown_candidate_id() -> None:
    """
    FK on backtest_outcomes.candidate_id must reject a non-existent UUID.
    This ensures referential integrity between the two backtest tables.
    """
    with PostgresContainer("postgres:15-alpine") as pg:
        db_url = pg.get_connection_url()
        _apply_migration(db_url)

        engine = create_engine(db_url)
        os.environ["DATABASE_URL"] = db_url

        fake_id = uuid.uuid4()
        outcome = _make_outcome(fake_id, profitable=False)

        with pytest.raises(IntegrityError):
            # FK violation — candidate_id does not exist in backtest_candidates
            record_outcome(outcome, engine)


@pytest.mark.integration
def test_migration_is_idempotent() -> None:
    """Applying the migration twice must not raise an error (IF NOT EXISTS guards)."""
    with PostgresContainer("postgres:15-alpine") as pg:
        db_url = pg.get_connection_url()
        _apply_migration(db_url)
        # Second application must succeed — all DDL uses IF NOT EXISTS
        _apply_migration(db_url)
