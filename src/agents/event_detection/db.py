"""
Database read/write for the Event Detection Agent.
PostgreSQL via SQLAlchemy. Schema TimescaleDB-compatible (ESOD Section 4.3).
"""

from __future__ import annotations

import logging

from sqlalchemy.engine import Engine

from src.agents.event_detection.models import DetectedEvent
from src.core.db import get_engine  # noqa: F401

logger = logging.getLogger(__name__)


def write_detected_events(events: list[DetectedEvent], engine: Engine) -> int:
    """
    Persist detected events to the detected_events table.

    Args:
        events: Validated DetectedEvent objects to insert.
        engine: SQLAlchemy Engine for the target database.

    Returns:
        Number of records successfully written.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "write_detected_events not yet implemented. "
        "TODO: Batch INSERT into detected_events table. "
        "Use detected_at column (TIMESTAMPTZ) for TimescaleDB compatibility."
    )


def read_recent_events(engine: Engine, limit: int = 100) -> list[DetectedEvent]:
    """
    Read the most recent detected events from the database.

    Args:
        engine: SQLAlchemy Engine.
        limit: Maximum number of events to return.

    Returns:
        List of DetectedEvent objects ordered by detected_at desc.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "read_recent_events not yet implemented. "
        "TODO: Query detected_events ORDER BY detected_at DESC LIMIT limit."
    )
