"""
Database read/write for the Feature Generation Agent.
PostgreSQL via SQLAlchemy. Schema TimescaleDB-compatible (ESOD Section 4.3).
"""

from __future__ import annotations

import logging

from sqlalchemy.engine import Engine

from src.agents.feature_generation.models import FeatureSet
from src.core.db import get_engine  # noqa: F401

logger = logging.getLogger(__name__)


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
