"""
Database read/write for the Strategy Evaluation Agent.
PostgreSQL via SQLAlchemy. Schema TimescaleDB-compatible (ESOD Section 4.3).
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.agents.strategy_evaluation.models import StrategyCandidate
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
