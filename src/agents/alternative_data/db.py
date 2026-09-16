"""
Database read/write for the Alternative Data Agent (Phase 3).

Handles persistence for three alternative signal tables:
    insider_trades     — SEC EDGAR Form 4 insider trades (issue #149)
    shipping_events    — tanker/vessel movement events (issue #153)
    narrative_signals  — Reddit/Stocktwits sentiment velocity (issues #151, #152)

All tables use TIMESTAMPTZ throughout (TimescaleDB-compatible).
Re-ingestion is idempotent:
    insider_trades    — no UNIQUE constraint; duplicates possible if same officer
                        files multiple transactions for the same instrument/date.
    shipping_events   — no UNIQUE constraint; same vessel may emit multiple events.
    narrative_signals — UNIQUE (instrument, platform, window_start); use
                        ON CONFLICT DO NOTHING to skip already-fetched windows.

sentiment vocabulary: the NarrativeSignal.sentiment field is the application-level
Sentiment enum (positive/neutral/negative), which does not match the
narrative_signals.sentiment CHECK constraint (bullish/bearish/neutral/mixed) —
the schema was written before the Sentiment enum existed (issue #148 predates
#151/#152). write_narrative_signal() translates via _SENTIMENT_DB_MAP rather
than altering the already-shipped enum or the table's CHECK constraint
(schema changes require human review — ESOD Hard Stop).

read_* functions remain stubs; not required by run_alternative_data_ingestion()
(issue #154) and out of scope until a caller needs them.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.agents.alternative_data.models import (
    InsiderTrade,
    NarrativeSignal,
    Sentiment,
    ShippingEvent,
)

logger = logging.getLogger(__name__)

# NarrativeSignal.sentiment (Sentiment enum) -> narrative_signals.sentiment CHECK vocabulary
_SENTIMENT_DB_MAP: dict[Sentiment, str] = {
    Sentiment.POSITIVE: "bullish",
    Sentiment.NEGATIVE: "bearish",
    Sentiment.NEUTRAL: "neutral",
}


# ---------------------------------------------------------------------------
# insider_trades
# ---------------------------------------------------------------------------


def write_insider_trades(records: list[InsiderTrade], engine: Engine) -> int:
    """
    Persist insider trade records to insider_trades table.

    Args:
        records: Validated InsiderTrade objects to insert.
        engine: SQLAlchemy Engine.

    Returns:
        Number of rows inserted.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on constraint violation or
            connection failure after logging the exception.
    """
    if not records:
        return 0

    fetched_at = datetime.now(tz=UTC)
    sql = text("""
        INSERT INTO insider_trades
            (instrument, trade_date, trade_type, shares, value_usd, officer_name,
             source, fetched_at)
        VALUES
            (:instrument, :trade_date, :trade_type, :shares, :value_usd, :officer_name,
             :source, :fetched_at)
        """)
    rows = [
        {
            "instrument": r.instrument,
            "trade_date": r.trade_date,
            "trade_type": r.trade_type,
            "shares": r.shares,
            "value_usd": r.value_usd,
            "officer_name": r.officer_name,
            "source": r.source,
            "fetched_at": fetched_at,
        }
        for r in records
    ]
    try:
        with engine.begin() as conn:
            conn.execute(sql, rows)
    except Exception:
        logger.exception("write_insider_trades failed; %d record(s) not persisted", len(records))
        raise

    logger.info("Wrote %d insider trade record(s) to insider_trades", len(records))
    return len(records)


def read_insider_trades(
    instrument: str,
    engine: Engine,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Read the most recent insider trade records for an instrument.

    Args:
        instrument: Ticker symbol (e.g. 'XOM').
        engine: SQLAlchemy Engine.
        limit: Maximum rows to return.

    Returns:
        List of dicts ordered by trade_date DESC.

    Raises:
        NotImplementedError: Until implemented in issue #149.
    """
    raise NotImplementedError("read_insider_trades not yet implemented — see issue #149")


# ---------------------------------------------------------------------------
# shipping_events
# ---------------------------------------------------------------------------


def write_shipping_events(records: list[ShippingEvent], engine: Engine) -> int:
    """
    Persist vessel/tanker movement events to shipping_events table.

    Args:
        records: Validated ShippingEvent objects to insert.
        engine: SQLAlchemy Engine.

    Returns:
        Number of rows inserted.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on constraint violation or
            connection failure after logging the exception.
    """
    if not records:
        return 0

    fetched_at = datetime.now(tz=UTC)
    sql = text("""
        INSERT INTO shipping_events
            (instrument, vessel_id, event_type, latitude, longitude, timestamp,
             source, fetched_at)
        VALUES
            (:instrument, :vessel_id, :event_type, :latitude, :longitude, :timestamp,
             :source, :fetched_at)
        """)
    rows = [
        {
            "instrument": r.instrument,
            "vessel_id": r.vessel_id,
            "event_type": r.event_type.value,
            "latitude": r.latitude,
            "longitude": r.longitude,
            "timestamp": r.timestamp,
            "source": r.source,
            "fetched_at": fetched_at,
        }
        for r in records
    ]
    try:
        with engine.begin() as conn:
            conn.execute(sql, rows)
    except Exception:
        logger.exception("write_shipping_events failed; %d record(s) not persisted", len(records))
        raise

    logger.info("Wrote %d shipping event record(s) to shipping_events", len(records))
    return len(records)


def read_shipping_events(
    engine: Engine,
    *,
    instrument: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Read recent shipping events, optionally filtered by affected instrument.

    Args:
        engine: SQLAlchemy Engine.
        instrument: Optional ticker to filter by (e.g. 'CL=F'). None returns all.
        limit: Maximum rows to return.

    Returns:
        List of dicts ordered by timestamp DESC.

    Raises:
        NotImplementedError: Until implemented in issue #153.
    """
    raise NotImplementedError("read_shipping_events not yet implemented — see issue #153")


# ---------------------------------------------------------------------------
# narrative_signals
# ---------------------------------------------------------------------------


def write_narrative_signal(record: NarrativeSignal, engine: Engine) -> int:
    """
    Persist a single narrative velocity signal to narrative_signals.

    Uses ON CONFLICT DO NOTHING on (instrument, platform, window_start) so
    re-fetching the same window is idempotent. record.sentiment (the
    application-level Sentiment enum) is translated to the table's
    bullish/bearish/neutral vocabulary via _SENTIMENT_DB_MAP.

    Args:
        record: Validated NarrativeSignal to insert.
        engine: SQLAlchemy Engine.

    Returns:
        1 if inserted, 0 if skipped due to conflict.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on constraint violation
            (other than the (instrument, platform, window_start) conflict,
            which is caught by ON CONFLICT DO NOTHING) or connection failure
            after logging the exception.
    """
    fetched_at = datetime.now(tz=UTC)
    sql = text("""
        INSERT INTO narrative_signals
            (instrument, platform, score, mention_count, sentiment,
             window_start, window_end, fetched_at)
        VALUES
            (:instrument, :platform, :score, :mention_count, :sentiment,
             :window_start, :window_end, :fetched_at)
        ON CONFLICT (instrument, platform, window_start) DO NOTHING
        """)
    params = {
        "instrument": record.instrument,
        "platform": record.platform,
        "score": record.score,
        "mention_count": record.mention_count,
        "sentiment": _SENTIMENT_DB_MAP[record.sentiment],
        "window_start": record.window_start,
        "window_end": record.window_end,
        "fetched_at": fetched_at,
    }
    try:
        with engine.begin() as conn:
            result = conn.execute(sql, params)
            inserted = result.rowcount
    except Exception:
        logger.exception(
            "write_narrative_signal failed for instrument=%s platform=%s",
            record.instrument,
            record.platform,
        )
        raise

    if inserted:
        logger.info(
            "Wrote narrative signal for instrument=%s platform=%s",
            record.instrument,
            record.platform,
        )
    else:
        logger.info(
            "Skipped narrative signal for instrument=%s platform=%s window_start=%s "
            "(already exists)",
            record.instrument,
            record.platform,
            record.window_start,
        )
    return max(inserted, 0)


def read_latest_narrative_signal(
    instrument: str,
    platform: str,
    engine: Engine,
) -> dict[str, Any] | None:
    """
    Read the most recent narrative signal for an instrument + platform pair.

    Args:
        instrument: Ticker symbol (e.g. 'USO').
        platform: 'reddit' | 'stocktwits' | 'combined'.
        engine: SQLAlchemy Engine.

    Returns:
        Dict of the most recent row, or None if no records exist.

    Raises:
        NotImplementedError: Until implemented in issues #151 / #152.
    """
    raise NotImplementedError(
        "read_latest_narrative_signal not yet implemented — see issues #151 / #152"
    )
