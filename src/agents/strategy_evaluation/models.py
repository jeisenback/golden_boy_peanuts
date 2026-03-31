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
    greeks: dict[str, float] | None = Field(
        default=None,
        description=(
            "BSM Greeks for the ATM leg(s) of this structure. "
            "Keys: 'delta', 'gamma', 'vega', 'theta', 'rho'. "
            "None when market_state is not available or option data is insufficient."
        ),
    )
    atm_strike: float | None = Field(
        default=None,
        description="ATM strike used for BSM computation (closest to spot at evaluation time).",
    )
    liquidity_ok: bool | None = Field(
        default=None,
        description=(
            "True if the ATM option meets minimum liquidity thresholds "
            "(volume ≥ MIN_OPTION_VOLUME and open_interest ≥ MIN_OPTION_OPEN_INTEREST). "
            "None when market_state is not available."
        ),
    )
