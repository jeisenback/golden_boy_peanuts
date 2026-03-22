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

Functions are stubs pending implementation in issues #149-#153.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# insider_trades
# ---------------------------------------------------------------------------


def write_insider_trades(records: list[dict[str, Any]], engine: Engine) -> int:
    """
    Persist insider trade records to insider_trades table.

    Args:
        records: List of dicts with keys:
            instrument (str), trade_date (datetime), trade_type (str),
            shares (int | None), value_usd (float | None),
            officer_name (str | None), source (str), fetched_at (datetime)
        engine: SQLAlchemy Engine.

    Returns:
        Number of rows inserted.

    Raises:
        NotImplementedError: Until implemented in issue #149.
    """
    raise NotImplementedError("write_insider_trades not yet implemented — see issue #149")


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


def write_shipping_events(records: list[dict[str, Any]], engine: Engine) -> int:
    """
    Persist vessel/tanker movement events to shipping_events table.

    Args:
        records: List of dicts with keys:
            instrument (str | None), vessel_id (str), event_type (str),
            latitude (float | None), longitude (float | None),
            timestamp (datetime), source (str), fetched_at (datetime)
        engine: SQLAlchemy Engine.

    Returns:
        Number of rows inserted.

    Raises:
        NotImplementedError: Until implemented in issue #153.
    """
    raise NotImplementedError("write_shipping_events not yet implemented — see issue #153")


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


def write_narrative_signal(record: dict[str, Any], engine: Engine) -> int:
    """
    Persist a single narrative velocity signal to narrative_signals.

    Uses ON CONFLICT DO NOTHING on (instrument, platform, window_start) so
    re-fetching the same window is idempotent.

    Args:
        record: Dict with keys:
            instrument (str), platform (str), score (float | None),
            mention_count (int | None), sentiment (str | None),
            window_start (datetime), window_end (datetime), fetched_at (datetime)
        engine: SQLAlchemy Engine.

    Returns:
        1 if inserted, 0 if skipped due to conflict.

    Raises:
        NotImplementedError: Until implemented in issues #151 / #152.
    """
    raise NotImplementedError("write_narrative_signal not yet implemented — see issues #151 / #152")


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
