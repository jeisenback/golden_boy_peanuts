"""
Backtesting pipeline for the Energy Options Opportunity Agent.

This module currently provides the DB layer for historical backtest data.
DB writers:   write_backtest_candidate(), record_outcome()

Planned entry point (issue #166):
  run_backtest_pipeline(slices) — calls compute_* functions directly, never
  run_feature_generation(), to avoid writing to the live feature_sets table.

Design notes (from eng review 2026-03-21):
  - backtest_candidates is isolated from strategy_candidates — historical replay
    rows never pollute production reporting queries.
  - profitable=None (not skipped) when yfinance returns no history for a date.
  - entry_premium/upper_strike/lower_strike are persisted for spread P&L even
    though Sprint A only backtests long_straddle — schema is forward-compatible.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
import uuid

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.backtest.models import BacktestCandidate, BacktestOutcome

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB writers
# ---------------------------------------------------------------------------


def write_backtest_candidate(candidate: BacktestCandidate, engine: Engine) -> uuid.UUID:
    """
    Persist a single BacktestCandidate to backtest_candidates and return
    the database-assigned UUID.

    Args:
        candidate: Validated BacktestCandidate to insert. candidate.signals
            (dict) is JSON-serialized internally before the INSERT — callers
            pass the raw dict and do not need to pre-serialize.
        engine:    SQLAlchemy Engine connected to the target database.

    Returns:
        uuid.UUID: The generated primary key assigned by gen_random_uuid().

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on constraint violation or
            connection failure after logging the exception.
    """
    sql = text(
        """
        INSERT INTO backtest_candidates
            (instrument, structure, snapshot_time, edge_score, signals, generated_at)
        VALUES
            (:instrument, :structure, :snapshot_time, :edge_score, :signals, :generated_at)
        RETURNING id
        """
    )

    params = {
        "instrument": candidate.instrument,
        "structure": candidate.structure,
        "snapshot_time": candidate.snapshot_time,
        "edge_score": candidate.edge_score,
        "signals": json.dumps(candidate.signals),
        "generated_at": candidate.generated_at,
    }

    try:
        with engine.begin() as conn:
            row = conn.execute(sql, params).fetchone()
    except Exception:
        logger.exception(
            "write_backtest_candidate failed for instrument=%s structure=%s",
            candidate.instrument,
            candidate.structure,
        )
        raise

    if row is None:  # pragma: no cover — INSERT RETURNING always returns a row
        raise RuntimeError("write_backtest_candidate: INSERT RETURNING returned no row")
    assigned_id: uuid.UUID = row[0]
    logger.debug(
        "Wrote backtest candidate id=%s instrument=%s edge_score=%.4f",
        assigned_id,
        candidate.instrument,
        candidate.edge_score,
    )
    return assigned_id


def record_outcome(outcome: BacktestOutcome, engine: Engine) -> uuid.UUID:
    """
    Persist a BacktestOutcome to backtest_outcomes and return its UUID.

    profitable=None is allowed — it means yfinance returned no data for the
    expiration date. The row is still inserted so the audit trail is complete.

    Args:
        outcome: Validated BacktestOutcome to insert.
        engine:  SQLAlchemy Engine connected to the target database.

    Returns:
        uuid.UUID: The generated primary key assigned by gen_random_uuid().

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on constraint violation or
            connection failure after logging the exception.
    """
    sql = text(
        """
        INSERT INTO backtest_outcomes
            (candidate_id, structure, expiration, underlying_close,
             entry_premium, upper_strike, lower_strike, profitable, recorded_at)
        VALUES
            (:candidate_id, :structure, :expiration, :underlying_close,
             :entry_premium, :upper_strike, :lower_strike, :profitable, :recorded_at)
        RETURNING id
        """
    )

    params = {
        "candidate_id": str(outcome.candidate_id),
        "structure": outcome.structure,
        "expiration": outcome.expiration,
        "underlying_close": outcome.underlying_close,
        "entry_premium": outcome.entry_premium,
        "upper_strike": outcome.upper_strike,
        "lower_strike": outcome.lower_strike,
        "profitable": outcome.profitable,
        "recorded_at": outcome.recorded_at or datetime.now(tz=UTC),
    }

    try:
        with engine.begin() as conn:
            row = conn.execute(sql, params).fetchone()
    except Exception:
        logger.exception(
            "record_outcome failed for candidate_id=%s expiration=%s",
            outcome.candidate_id,
            outcome.expiration,
        )
        raise

    if row is None:  # pragma: no cover — INSERT RETURNING always returns a row
        raise RuntimeError("record_outcome: INSERT RETURNING returned no row")
    assigned_id: uuid.UUID = row[0]
    logger.debug(
        "Recorded outcome id=%s candidate_id=%s profitable=%s",
        assigned_id,
        outcome.candidate_id,
        outcome.profitable,
    )
    return assigned_id
