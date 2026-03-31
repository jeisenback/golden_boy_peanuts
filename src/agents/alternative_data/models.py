"""
Pydantic models for the Alternative Data Agent (Phase 3).

All external feed data must be validated through these models before
any downstream processing (ESOD Section 6).

API boundary models (issue #183):
  - EDGAR: EftsHit, EftsSearchResponse, FilingIndexItem, FilingIndexResponse
  - Reddit: RedditPost, RedditSearchResponse
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

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


# ---------------------------------------------------------------------------
# EDGAR API boundary models (issue #183, ESOD §6)
# ---------------------------------------------------------------------------


class _EftsHitSource(BaseModel):
    """Validated _source field from an EDGAR EFTS search hit."""

    entity_id: str = ""


class EftsHit(BaseModel):
    """
    Validated single hit from the EDGAR EFTS full-text search API.

    Field aliases map JSON keys that start with underscore (_id, _source)
    to Python-friendly attribute names (id, source).
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id", default="")
    source: _EftsHitSource = Field(alias="_source", default_factory=_EftsHitSource)


class _EftsHitsInner(BaseModel):
    """Inner hits envelope from the EFTS response (``hits.hits``)."""

    hits: list[EftsHit]


class EftsSearchResponse(BaseModel):
    """Top-level EFTS search API response envelope."""

    hits: _EftsHitsInner


class FilingIndexItem(BaseModel):
    """Single item in an EDGAR filing directory index."""

    name: str


class _FilingIndexDirectory(BaseModel):
    """Directory envelope in the EDGAR filing index JSON response."""

    item: list[FilingIndexItem]


class FilingIndexResponse(BaseModel):
    """EDGAR filing index JSON response (``{accession}-index.json``)."""

    directory: _FilingIndexDirectory


# ---------------------------------------------------------------------------
# Reddit API boundary models (issue #183, ESOD §6)
# ---------------------------------------------------------------------------


class RedditPost(BaseModel):
    """Single Reddit post extracted from search results."""

    title: str
    selftext: str = ""
    score: int = 0


class _RedditPostChild(BaseModel):
    """Child envelope wrapping a Reddit post in the search response."""

    data: RedditPost


class _RedditSearchData(BaseModel):
    """Data envelope in the Reddit search API response."""

    children: list[_RedditPostChild]


class RedditSearchResponse(BaseModel):
    """Top-level Reddit public JSON API search response envelope."""

    data: _RedditSearchData
