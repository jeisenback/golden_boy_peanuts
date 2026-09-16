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
    generated_at: datetime = Field(..., description="UTC timestamp when candidate was generated")


class StrategyOutcome(BaseModel):
    """
    Actual price movement after a strategy candidate was generated (issue #130).

    price_at_expiration and pct_move are nullable — populated by a reconciliation
    job after the candidate's expiration date passes.
    """

    candidate_id: int = Field(..., description="FK to strategy_candidates.id")
    instrument: str
    structure: str
    generated_at: datetime
    expiration_date: datetime
    price_at_generation: float
    price_at_expiration: float | None = None
    pct_move: float | None = None
    recorded_at: datetime = Field(..., description="UTC timestamp when outcome was recorded")
