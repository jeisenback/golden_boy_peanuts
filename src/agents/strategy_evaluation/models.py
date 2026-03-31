"""
Pydantic models for the Strategy Evaluation Agent.

StrategyCandidate fields match PRD Section 9 output schema exactly:
  instrument, structure, expiration, edge_score, signals, generated_at
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.agents.ingestion.models import OptionStructure


class StrategyOutcome(BaseModel):
    """
    Outcome record for a strategy candidate — tracks actual price move at expiration.

    price_at_expiration and pct_move are nullable until the expiration job
    resolves them from market data.  The table is append-only; use
    write_strategy_outcome() to insert or update a single row.
    """

    candidate_id: int = Field(..., gt=0, description="FK to strategy_candidates.id")
    instrument: str = Field(..., description="Target instrument ticker, e.g. 'USO'")
    structure: OptionStructure
    generated_at: datetime = Field(..., description="UTC timestamp from the source candidate")
    expiration_date: datetime = Field(..., description="Target expiration as UTC datetime")
    price_at_generation: float = Field(
        ..., description="Underlying price when the candidate was generated"
    )
    price_at_expiration: float | None = Field(
        None, description="Underlying price at expiration; None until recorded by expiration job"
    )
    pct_move: float | None = Field(
        None, description="Percentage move from generation to expiration; None until recorded"
    )
    recorded_at: datetime = Field(..., description="UTC timestamp when this record was written")


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
