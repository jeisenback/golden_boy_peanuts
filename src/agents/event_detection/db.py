"""
Database read/write for the Event Detection Agent.
PostgreSQL via SQLAlchemy. Schema TimescaleDB-compatible (ESOD Section 4.3).
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.agents.event_detection.models import DetectedEvent, EIAInventoryRecord
from src.core.db import get_engine  # noqa: F401

logger = logging.getLogger(__name__)


def write_detected_events(events: list[DetectedEvent], engine: Engine) -> int:
    """
    Persist detected events to the detected_events table.

    Idempotent: ON CONFLICT (event_id) DO NOTHING — re-classifying the same
    article URL produces no duplicate rows.

    Args:
        events: Validated DetectedEvent objects to insert.
        engine: SQLAlchemy Engine for the target database.

    Returns:
        Number of records submitted for insertion (including no-op conflicts).

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on connection failure or
            unexpected constraint violation after logging the exception.
    """
    if not events:
        return 0

    sql = text("""
        INSERT INTO detected_events
            (event_id, event_type, description, source, confidence_score,
             intensity, detected_at, affected_instruments, raw_headline)
        VALUES
            (:event_id, :event_type, :description, :source, :confidence_score,
             :intensity, :detected_at, :affected_instruments, :raw_headline)
        ON CONFLICT (event_id) DO NOTHING
        """)
    rows = [
        {
            "event_id": e.event_id,
            "event_type": e.event_type.value,
            "description": e.description,
            "source": e.source,
            "confidence_score": e.confidence_score,
            "intensity": e.intensity.value,
            "detected_at": e.detected_at,
            "affected_instruments": json.dumps(e.affected_instruments),
            "raw_headline": e.raw_headline,
        }
        for e in events
    ]
    try:
        with engine.begin() as conn:
            conn.execute(sql, rows)
    except Exception:
        logger.exception("write_detected_events failed; %d event(s) not persisted", len(events))
        raise

    logger.info("write_detected_events: submitted %d event(s) to detected_events", len(events))
    return len(events)


def read_recent_events(engine: Engine, limit: int = 100) -> list[DetectedEvent]:
    """
    Read the most recent detected events from the database.

    Args:
        engine: SQLAlchemy Engine.
        limit: Maximum number of events to return (default 100).

    Returns:
        List of DetectedEvent objects ordered by detected_at DESC.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on connection failure after
            logging the exception.
    """
    sql = text("""
        SELECT event_id, event_type, description, source, confidence_score,
               intensity, detected_at, affected_instruments, raw_headline
        FROM detected_events
        ORDER BY detected_at DESC
        LIMIT :limit
        """)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, {"limit": limit}).mappings().all()
    except Exception:
        logger.exception("read_recent_events failed")
        raise

    return [
        DetectedEvent(
            event_id=row["event_id"],
            event_type=row["event_type"],
            description=row["description"],
            source=row["source"],
            confidence_score=float(row["confidence_score"]),
            intensity=row["intensity"],
            detected_at=row["detected_at"],
            affected_instruments=row["affected_instruments"] or [],
            raw_headline=row["raw_headline"],
        )
        for row in rows
    ]


def write_eia_records(records: list[EIAInventoryRecord], engine: Engine) -> int:
    """
    Persist EIA inventory records to the eia_inventory table.

    Idempotent: ON CONFLICT (period) DO NOTHING — re-ingesting the same
    reporting week produces no duplicate rows.

    Args:
        records: Validated EIAInventoryRecord objects to insert.
        engine: SQLAlchemy Engine for the target database.

    Returns:
        Number of records submitted for insertion (including no-op conflicts).

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on connection failure or
            unexpected constraint violation after logging the exception.
    """
    if not records:
        return 0

    sql = text("""
        INSERT INTO eia_inventory
            (period, crude_stocks_mb, refinery_utilization_pct, source, fetched_at)
        VALUES
            (:period, :crude_stocks_mb, :refinery_utilization_pct, :source, :fetched_at)
        ON CONFLICT (period) DO NOTHING
        """)
    rows = [
        {
            "period": r.period,
            "crude_stocks_mb": r.crude_stocks_mb,
            "refinery_utilization_pct": r.refinery_utilization_pct,
            "source": r.source,
            "fetched_at": r.fetched_at,
        }
        for r in records
    ]
    try:
        with engine.begin() as conn:
            conn.execute(sql, rows)
    except Exception:
        logger.exception("write_eia_records failed; %d record(s) not persisted", len(records))
        raise

    logger.info("write_eia_records: submitted %d record(s) to eia_inventory", len(records))
    return len(records)
