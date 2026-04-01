"""
Pydantic models for the Strategy Evaluation Agent.

StrategyCandidate fields match PRD Section 9 output schema exactly:
  instrument, structure, expiration, edge_score, signals, generated_at

Extended with optional BSM Greeks (attached by evaluate_strategies when
market_state is provided — Phase 3 options platform addition).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.agents.ingestion.models import OptionStructure
from src.core.bsm import BSMGreeks


class StrategyCandidate(BaseModel):
    """
    Single ranked strategy opportunity (PRD Section 9 output schema).

    The optional `greeks` field is populated by evaluate_strategies() when
    a MarketState with live options data is passed in. When greeks is None
    the candidate is still valid — it means BSM computation was skipped
    (no ATM implied vol available or structure is calendar_spread).
    """

    model_config = {"arbitrary_types_allowed": True}

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
    greeks: BSMGreeks | None = Field(
        default=None,
        description=(
            "Net BSM Greeks for the strategy position. Populated when market_state is "
            "passed to evaluate_strategies(). None if BSM computation was skipped."
        ),
    )
