"""
Pydantic models for the Alternative Data Agent (Phase 3).

All external feed data must be validated through these models before
any downstream processing (ESOD Section 6).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from src.core.compat import StrEnum


class TradeType(StrEnum):
    """Supported insider trade types (matches insider_trades.trade_type CHECK constraint)."""

    BUY = "buy"
    SELL = "sell"
    GRANT = "grant"
    EXERCISE = "exercise"


class InsiderTrade(BaseModel):
    """
    Validated insider trade record from SEC EDGAR Form 4.

    Maps to the insider_trades table schema (db/schema.sql).
    Missing or optional fields are allowed to be None — partial
    filings are persisted rather than dropped (ESOD §6).
    """

    instrument: str
    trade_date: datetime
    trade_type: str
    shares: int | None = None
    value_usd: float | None = None
    officer_name: str | None = None
    source: str = "edgar"


class Sentiment(StrEnum):
    """Sentiment classifications for narrative signal records."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class NarrativeSignal(BaseModel):
    """
    Validated narrative/sentiment signal from a social platform.

    Maps to the narrative_signals table schema (db/schema.sql).
    score is the aggregate net upvote/mention score across all matching
    posts in the window. sentiment is derived from a keyword heuristic.
    """

    instrument: str
    platform: str = "reddit"
    score: int
    mention_count: int
    sentiment: Sentiment
    window_start: datetime
    window_end: datetime
    source: str = "reddit"
