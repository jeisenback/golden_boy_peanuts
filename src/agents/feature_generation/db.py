"""
Database read/write for the Feature Generation Agent.
PostgreSQL via SQLAlchemy. Schema TimescaleDB-compatible (ESOD Section 4.3).
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from src.agents.feature_generation.models import FeatureSet

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


def write_feature_set(feature_set: FeatureSet, engine: Engine) -> None:
    """
    Persist a computed FeatureSet to the feature_sets table.

    Args:
        feature_set: Validated FeatureSet to persist.
        engine: SQLAlchemy Engine.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "write_feature_set not yet implemented. "
        "TODO: INSERT into feature_sets table. "
        "Use snapshot_time (TIMESTAMPTZ) for TimescaleDB compatibility."
    )


def read_latest_feature_set(engine: Engine) -> FeatureSet | None:
    """
    Read the most recently computed FeatureSet from the database.

    Returns:
        Most recent FeatureSet, or None if no data exists.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "read_latest_feature_set not yet implemented. "
        "TODO: Query feature_sets ORDER BY snapshot_time DESC LIMIT 1."
    )
