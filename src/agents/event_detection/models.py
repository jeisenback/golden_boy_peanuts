"""
Pydantic models for the Event Detection Agent data boundary (ESOD Section 6).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.core.compat import StrEnum


class EventType(StrEnum):
    """Categories of energy market events."""

    SUPPLY_DISRUPTION = "supply_disruption"
    REFINERY_OUTAGE = "refinery_outage"
    TANKER_CHOKEPOINT = "tanker_chokepoint"
    GEOPOLITICAL = "geopolitical"
    SANCTIONS = "sanctions"
    UNKNOWN = "unknown"


class EventIntensity(StrEnum):
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


class EIAInventoryRecord(BaseModel):
    """
    Weekly EIA petroleum status report record.

    Stores crude oil stocks and refinery utilization for one reporting period.
    period follows EIA format: 'YYYY-WW' (e.g. '2024-10' for week 10 of 2024).
    """

    period: str = Field(..., description="EIA reporting period, e.g. '2024-10'")
    crude_stocks_mb: float | None = Field(
        default=None, description="U.S. crude oil stocks in millions of barrels"
    )
    refinery_utilization_pct: float | None = Field(
        default=None, description="Refinery utilization rate as a percentage"
    )
    source: str = Field(default="eia", description="Data source identifier")
    fetched_at: datetime = Field(..., description="UTC timestamp of the fetch")
