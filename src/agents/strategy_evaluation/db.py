"""
Database read/write for the Strategy Evaluation Agent.
PostgreSQL via SQLAlchemy. Schema TimescaleDB-compatible (ESOD Section 4.3).
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.agents.strategy_evaluation.models import StrategyCandidate, StrategyOutcome
from src.core.db import get_engine  # noqa: F401

logger = logging.getLogger(__name__)


def write_strategy_candidates(candidates: list[StrategyCandidate], engine: Engine) -> int:
    """
    Persist ranked strategy candidates to strategy_candidates table.

    signals is stored as JSONB. structure is stored as the StrEnum string value.

    Args:
        candidates: Validated StrategyCandidate objects to insert.
        engine: SQLAlchemy Engine.

    Returns:
        Number of records written.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on constraint violation or
            connection failure after logging the exception.
    """
    if not candidates:
        return 0

    sql = text("""
        INSERT INTO strategy_candidates
            (instrument, structure, expiration, edge_score, signals, generated_at)
        VALUES
            (:instrument, :structure, :expiration, :edge_score, :signals, :generated_at)
        """)
    rows = [
        {
            "instrument": c.instrument,
            "structure": c.structure.value,
            "expiration": c.expiration,
            "edge_score": c.edge_score,
            "signals": json.dumps(c.signals),
            "generated_at": c.generated_at,
        }
        for c in candidates
    ]
    try:
        with engine.begin() as conn:
            conn.execute(sql, rows)
    except Exception:
        logger.exception(
            "write_strategy_candidates failed; %d record(s) not persisted", len(candidates)
        )
        raise

    logger.info("Wrote %d strategy candidate(s) to strategy_candidates", len(candidates))
    return len(candidates)


def read_top_candidates(engine: Engine, limit: int = 10) -> list[StrategyCandidate]:
    """
    Read the most recent top-ranked strategy candidates.

    Args:
        engine: SQLAlchemy Engine.
        limit: Maximum number of candidates to return.

    Returns:
        List of StrategyCandidate ordered by edge_score DESC, then generated_at DESC.

    Raises:
        NotImplementedError: Until implemented.
    """
    sql = text("""
        SELECT instrument, structure, expiration, edge_score, signals, generated_at
        FROM strategy_candidates
        ORDER BY edge_score DESC, generated_at DESC
        LIMIT :limit
        """)

    with engine.connect() as conn:
        rows = conn.execute(sql, {"limit": limit}).fetchall()

    result: list[StrategyCandidate] = []
    from src.agents.ingestion.models import OptionStructure

    for row in rows:
        instrument = row[0]
        structure_raw = row[1]
        expiration = int(row[2])
        edge_score = float(row[3])
        signals_raw = row[4]
        generated_at = row[5]

        signals = signals_raw if isinstance(signals_raw, dict) else json.loads(signals_raw or "{}")

        try:
            structure = OptionStructure(structure_raw)
        except Exception:
            logger.warning(
                "read_top_candidates: unknown structure value %r for instrument %s; "
                "falling back to LONG_STRADDLE",
                structure_raw,
                instrument,
            )
            structure = OptionStructure.LONG_STRADDLE

        try:
            candidate = StrategyCandidate(
                instrument=instrument,
                structure=structure,
                expiration=expiration,
                edge_score=edge_score,
                signals=signals,
                generated_at=generated_at,
            )
        except Exception:
            logger.warning(
                "read_top_candidates: skipping malformed row for instrument %s "
                "(edge_score=%s, structure=%s)",
                instrument,
                edge_score,
                structure,
                exc_info=True,
            )
            continue
        result.append(candidate)

    return result


def write_strategy_outcome(outcome: StrategyOutcome, engine: Engine) -> int:
    """
    Insert or upsert a single strategy outcome record.

    If a row with the same candidate_id already exists, update the price and
    move fields (idempotent reconciliation).

    Args:
        outcome: Validated StrategyOutcome to persist.
        engine: SQLAlchemy Engine.

    Returns:
        1 on success.
    """
    sql = text("""
        INSERT INTO strategy_outcomes
            (candidate_id, instrument, structure, generated_at,
             expiration_date, price_at_generation, price_at_expiration,
             pct_move, recorded_at)
        VALUES
            (:candidate_id, :instrument, :structure, :generated_at,
             :expiration_date, :price_at_generation, :price_at_expiration,
             :pct_move, :recorded_at)
        ON CONFLICT (candidate_id) DO UPDATE SET
            price_at_expiration = EXCLUDED.price_at_expiration,
            pct_move            = EXCLUDED.pct_move,
            recorded_at         = EXCLUDED.recorded_at
        """)
    params = {
        "candidate_id": outcome.candidate_id,
        "instrument": outcome.instrument,
        "structure": outcome.structure,
        "generated_at": outcome.generated_at,
        "expiration_date": outcome.expiration_date,
        "price_at_generation": outcome.price_at_generation,
        "price_at_expiration": outcome.price_at_expiration,
        "pct_move": outcome.pct_move,
        "recorded_at": outcome.recorded_at,
    }
    try:
        with engine.begin() as conn:
            conn.execute(sql, params)
    except Exception:
        logger.exception("write_strategy_outcome failed for candidate_id=%s", outcome.candidate_id)
        raise

    logger.info("Wrote strategy outcome for candidate_id=%s", outcome.candidate_id)
    return 1


def fetch_pending_outcomes(engine: Engine) -> list[dict[str, object]]:
    """
    Return strategy candidates past their expiration date with no recorded outcome,
    or with a provisional outcome (price_at_expiration still NULL).

    Each returned dict contains: id, instrument, structure, expiration,
    edge_score, generated_at — enough for the reconciliation job to fetch
    realized prices and write an outcome.

    Args:
        engine: SQLAlchemy Engine.

    Returns:
        List of dicts, one per pending candidate.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on connection failure
            after logging the exception.
    """
    # Column concatenation (sc.expiration || ' days') is safe — the value
    # comes from our own strategy_candidates table, not from user input.
    sql = text("""
        SELECT sc.id, sc.instrument, sc.structure, sc.expiration,
               sc.edge_score, sc.generated_at
        FROM strategy_candidates sc
        LEFT JOIN strategy_outcomes so ON so.candidate_id = sc.id
        WHERE (so.id IS NULL OR so.price_at_expiration IS NULL)
          AND sc.generated_at + (sc.expiration || ' days')::INTERVAL < now()
        ORDER BY sc.generated_at ASC
        """)

    try:
        with engine.connect() as conn:
            rows = conn.execute(sql).fetchall()
    except Exception:
        logger.exception("fetch_pending_outcomes failed")
        raise

    return [
        {
            "id": row[0],
            "instrument": row[1],
            "structure": row[2],
            "expiration": row[3],
            "edge_score": float(row[4]),
            "generated_at": row[5],
        }
        for row in rows
    ]
