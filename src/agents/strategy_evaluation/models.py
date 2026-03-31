"""
Pydantic models for the Strategy Evaluation Agent.

StrategyCandidate fields match PRD Section 9 output schema exactly:
  instrument, structure, expiration, edge_score, signals, generated_at
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.agents.ingestion.models import OptionStructure


class StrategyCandidate(BaseModel):
    """
    Single ranked strategy opportunity (PRD Section 9 output schema).
    """

    instrument: str = Field(..., description="Target instrument ticker, e.g. 'USO', 'XLE'")
    structure: OptionStructure
    expiration: int = Field(..., gt=0, description="Target expiration in calendar days")
    edge_score: float = Field(..., ge=0.0, le=1.0, description="Composite opportunity score")
    signals: dict[str, str] = Field(
        ...,
        description=(
            "Contributing signal map. "
            "Example: {'volatility_gap': 'positive', 'tanker_disruption_index': 'high'}"
        ),
    )
    data_quality: dict[str, str] = Field(
        ...,
        description=(
            "Signal availability map. Keys match signal names; values are one of "
            "'available' (signal computed with real data), "
            "'defaulted_zero' (signal present but exactly 0.0), or "
            "'unavailable' (signal could not be computed — treated as 0 in edge score)."
        ),
    )
    generated_at: datetime = Field(..., description="UTC timestamp when candidate was generated")
