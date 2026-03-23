"""
Database read/write for the Strategy Evaluation Agent.
PostgreSQL via SQLAlchemy. Schema TimescaleDB-compatible (ESOD Section 4.3).
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from typing import Any

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


def write_strategy_outcome(outcome: StrategyOutcome, engine: Engine) -> None:
    """
    Insert or upsert a single strategy outcome record.

    Uses ON CONFLICT (candidate_id) DO UPDATE so the expiration-price job can
    fill in price_at_expiration and pct_move on a subsequent call without
    creating a duplicate row.

    Args:
        outcome: Validated StrategyOutcome to persist.
        engine: SQLAlchemy Engine.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on constraint violation or
            connection failure after logging the exception.
    """
    sql = text("""
        INSERT INTO strategy_outcomes
            (candidate_id, instrument, structure, generated_at, expiration_date,
             price_at_generation, price_at_expiration, pct_move, recorded_at)
        VALUES
            (:candidate_id, :instrument, :structure, :generated_at, :expiration_date,
             :price_at_generation, :price_at_expiration, :pct_move, :recorded_at)
        ON CONFLICT (candidate_id) DO UPDATE SET
            price_at_expiration = EXCLUDED.price_at_expiration,
            pct_move            = EXCLUDED.pct_move,
            recorded_at         = EXCLUDED.recorded_at
        """)
    row: dict[str, Any] = {
        "candidate_id": outcome.candidate_id,
        "instrument": outcome.instrument,
        "structure": outcome.structure.value,
        "generated_at": outcome.generated_at,
        "expiration_date": outcome.expiration_date,
        "price_at_generation": outcome.price_at_generation,
        "price_at_expiration": outcome.price_at_expiration,
        "pct_move": outcome.pct_move,
        "recorded_at": outcome.recorded_at,
    }
    try:
        with engine.begin() as conn:
            conn.execute(sql, row)
    except Exception:
        logger.exception("write_strategy_outcome failed for candidate_id=%s", outcome.candidate_id)
        raise

    logger.info(
        "Wrote outcome for candidate_id=%s instrument=%s",
        outcome.candidate_id,
        outcome.instrument,
    )


def fetch_pending_outcomes(
    engine: Engine,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Return strategy candidates past their expiration date with no recorded outcome.

    Queries strategy_candidates LEFT JOIN strategy_outcomes and returns rows
    where the outcome has not yet been recorded and the computed expiration date
    (generated_at + expiration days) is before as_of.

    Args:
        engine: SQLAlchemy Engine.
        as_of: Treat this datetime as "now" for expiration comparisons.
            Defaults to datetime.now(UTC). Pass an explicit value in tests.

    Returns:
        List of dicts with keys: candidate_id, instrument, structure,
        generated_at, expiration_date — ready to be passed to a price-fetch job
        that will call write_strategy_outcome() with the resolved prices.
    """
    sql = text("""
        SELECT
            sc.id           AS candidate_id,
            sc.instrument,
            sc.structure,
            sc.generated_at,
            (sc.generated_at + sc.expiration * INTERVAL '1 day')::TIMESTAMPTZ
                            AS expiration_date
        FROM  strategy_candidates sc
        LEFT JOIN strategy_outcomes so ON so.candidate_id = sc.id
        WHERE so.candidate_id IS NULL
          AND (sc.generated_at + sc.expiration * INTERVAL '1 day') < :as_of
        ORDER BY expiration_date ASC
        """)
    cutoff = as_of if as_of is not None else datetime.now(tz=UTC)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"as_of": cutoff}).mappings().all()
    return [dict(row) for row in rows]
