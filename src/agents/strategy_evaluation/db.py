"""
Database read/write for the Strategy Evaluation Agent.
PostgreSQL via SQLAlchemy. Schema TimescaleDB-compatible (ESOD Section 4.3).
"""
from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from src.agents.strategy_evaluation.models import StrategyCandidate

logger = logging.getLogger(__name__)


def get_engine() -> Engine:
    """
    Create a SQLAlchemy engine from DATABASE_URL environment variable.

    Raises:
        RuntimeError: If DATABASE_URL is not set.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    return create_engine(database_url, pool_pre_ping=True)


def write_strategy_candidates(
    candidates: list[StrategyCandidate], engine: Engine
) -> int:
    """
    Persist ranked strategy candidates to strategy_candidates table.

    Args:
        candidates: Validated StrategyCandidate objects to insert.
        engine: SQLAlchemy Engine.

    Returns:
        Number of records written.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "write_strategy_candidates not yet implemented. "
        "TODO: Batch INSERT into strategy_candidates table. "
        "Use generated_at (TIMESTAMPTZ) for TimescaleDB compatibility."
    )


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
    raise NotImplementedError(
        "read_top_candidates not yet implemented. "
        "TODO: Query strategy_candidates ORDER BY edge_score DESC, generated_at DESC LIMIT limit."
    )
