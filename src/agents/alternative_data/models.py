"""
Pydantic models for the Alternative Data Agent (Phase 3).

All external feed data must be validated through these models before
any downstream processing (ESOD Section 6).

Includes boundary models for raw API responses (EDGAR EFTS, Reddit
search, filing index) so that malformed external data raises
pydantic.ValidationError rather than silently returning defaults.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.core.compat import StrEnum


class TradeType(StrEnum):
    """Supported insider trade types (matches insider_trades.trade_type CHECK constraint)."""

    BUY = "buy"
    SELL = "sell"
    GRANT = "grant"
    EXERCISE = "exercise"


class QuiverInsiderRow(BaseModel):
    """
    Raw row from Quiver Quantitative ``/beta/live/insiders/{ticker}`` API.

    All fields are optional — the Pydantic boundary validates the shape before
    any field access in ``_parse_quiver_row`` (ESOD §6).
    """

    Transaction: str | None = None
    Date: str | None = None
    Name: str | None = None
    Shares: float | None = None  # API may return float; cast to int downstream
    Price: float | None = None


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


# ---------------------------------------------------------------------------
# EDGAR EFTS API boundary models (issue #183)
# ---------------------------------------------------------------------------


class EftsSource(BaseModel):
    """_source object inside an EFTS hit."""

    entity_id: str


class EftsHit(BaseModel):
    """Single hit from EFTS search-index response."""

    id: str = Field(alias="_id")
    source: EftsSource = Field(alias="_source")

    model_config = {"populate_by_name": True}


class EftsHitsContainer(BaseModel):
    """Wrapper for the hits.hits array in EFTS response."""

    hits: list[EftsHit] = Field(default_factory=list)


class EftsSearchResponse(BaseModel):
    """Top-level EFTS search-index JSON response."""

    hits: EftsHitsContainer


class FilingIndexItem(BaseModel):
    """Single item in an EDGAR filing index directory."""

    name: str


class FilingIndexDirectory(BaseModel):
    """directory object in an EDGAR filing index response."""

    item: list[FilingIndexItem] = Field(default_factory=list)


class FilingIndexResponse(BaseModel):
    """Top-level EDGAR filing index JSON response."""

    directory: FilingIndexDirectory


# ---------------------------------------------------------------------------
# Reddit API boundary models (issue #183)
# ---------------------------------------------------------------------------


class RedditPost(BaseModel):
    """Data payload of a single Reddit search result child."""

    title: str
    selftext: str = ""
    score: int = 0


class RedditChild(BaseModel):
    """Single child entry in Reddit search response."""

    data: RedditPost


class RedditData(BaseModel):
    """data envelope of a Reddit search response."""

    children: list[RedditChild] = Field(default_factory=list)


class RedditSearchResponse(BaseModel):
    """Top-level Reddit search JSON response."""

    data: RedditData
