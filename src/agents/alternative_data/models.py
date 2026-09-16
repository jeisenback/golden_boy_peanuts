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


class EventType(StrEnum):
    """Vessel event types for shipping_events table (matches DB event_type values)."""

    TRANSIT = "transit"
    ANCHORED = "anchored"
    DELAYED = "delayed"


class ShippingEvent(BaseModel):
    """
    Validated vessel movement event near an energy supply chokepoint.

    Maps to the shipping_events table schema (db/schema.sql).
    instrument is nullable — a vessel in a chokepoint zone may affect
    multiple instruments or none specifically.
    """

    vessel_id: str
    event_type: EventType
    latitude: float
    longitude: float
    timestamp: datetime
    source: str = "marinetraffic"
    instrument: str | None = None


class MarineTrafficVessel(BaseModel):
    """
    Raw vessel record from MarineTraffic ``getVesselsInArea`` API.

    Validates the response shape at the module boundary before any field
    access in ``_vessel_to_shipping_event`` (ESOD §6). The API returns
    LAT/LON/SPEED/TIMESTAMP as strings; Pydantic coerces them to numeric
    types here rather than at each call site.
    """

    MMSI: str
    LAT: float
    LON: float
    SPEED: float = 0.0
    TIMESTAMP: int | None = None
