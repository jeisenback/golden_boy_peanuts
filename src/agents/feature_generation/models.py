"""
Pydantic models for the Feature Generation Agent data boundary (ESOD Section 6).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class VolatilityGap(BaseModel):
    """Realized vs. implied volatility gap for a given instrument."""

    instrument: str
    realized_vol: float = Field(..., ge=0.0, description="Realized volatility (annualized)")
    implied_vol: float = Field(..., ge=0.0, description="Implied volatility (annualized)")
    gap: float = Field(..., description="implied_vol - realized_vol; positive = IV premium")
    computed_at: datetime


class FeatureSet(BaseModel):
    """
    Complete set of derived signals for one market evaluation cycle.

    Primary output of Feature Generation Agent; primary input to Strategy Evaluation Agent.
    """

    snapshot_time: datetime
    volatility_gaps: list[VolatilityGap] = Field(default_factory=list)
    futures_curve_steepness: float | None = Field(
        default=None, description="WTI futures curve slope; positive = contango"
    )
    sector_dispersion: float | None = Field(
        default=None, description="Price dispersion across XOM, CVX, USO, XLE"
    )
    insider_conviction_score: float | None = Field(default=None, ge=0.0, le=1.0)
    narrative_velocity: float | None = Field(
        default=None, ge=0.0, description="Headline acceleration score"
    )
    supply_shock_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    tanker_disruption_index: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Maritime shipping disruption risk"
    )
    feature_errors: list[str] = Field(
        default_factory=list,
        description="Non-fatal errors during feature computation",
    )
