"""
Pydantic models for the Event Detection Agent data boundary (ESOD Section 6).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Categories of energy market events."""

    SUPPLY_DISRUPTION = "supply_disruption"
    REFINERY_OUTAGE = "refinery_outage"
    TANKER_CHOKEPOINT = "tanker_chokepoint"
    GEOPOLITICAL = "geopolitical"
    SANCTIONS = "sanctions"
    UNKNOWN = "unknown"


class EventIntensity(str, Enum):
    """Intensity level assigned to a detected event."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DetectedEvent(BaseModel):
    """
    Single energy market event detected and scored by the Event Detection Agent.

    Used as input to the Feature Generation Agent for signal computation.
    """

    event_id: str = Field(..., description="Unique identifier for this event")
    event_type: EventType
    description: str = Field(..., description="Summary of the detected event")
    source: str = Field(..., description="Data source (e.g., 'newsapi', 'gdelt')")
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    intensity: EventIntensity
    detected_at: datetime = Field(..., description="UTC timestamp of detection")
    affected_instruments: list[str] = Field(default_factory=list)
    raw_headline: str | None = Field(default=None)
