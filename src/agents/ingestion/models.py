"""
Pydantic models for the Ingestion Agent data boundary (ESOD Section 6).
All external feed data must be validated through these models before
any downstream processing.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.core.compat import StrEnum


class InstrumentType(StrEnum):
    """Supported instrument types (PRD Section 3.1)."""

    CRUDE_FUTURES = "crude_futures"
    ETF = "etf"
    EQUITY = "equity"
    OPTIONS_CHAIN = "options_chain"


class OptionStructure(StrEnum):
    """Supported option structures for the MVP (PRD Section 3.2)."""

    LONG_STRADDLE = "long_straddle"
    CALL_SPREAD = "call_spread"
    PUT_SPREAD = "put_spread"
    CALENDAR_SPREAD = "calendar_spread"


class RawPriceRecord(BaseModel):
    """
    Validated raw price record from any market data feed.

    Malformed records are logged and quarantined, never silently dropped (ESOD 6).
    """

    instrument: str = Field(..., description="Ticker symbol, e.g. 'USO', 'CL=F', 'XOM'")
    instrument_type: InstrumentType
    price: float = Field(..., gt=0.0, description="Current price; must be positive")
    volume: int | None = Field(default=None, ge=0)
    timestamp: datetime = Field(..., description="UTC timestamp of the price record")
    source: str = Field(..., description="Data source identifier, e.g. 'alpha_vantage'")


class OptionRecord(BaseModel):
    """Single options chain record."""

    instrument: str = Field(..., description="Underlying instrument ticker")
    strike: float = Field(..., gt=0.0)
    expiration_date: datetime = Field(..., description="Option expiration date (UTC)")
    implied_volatility: float | None = Field(default=None, ge=0.0)
    open_interest: int | None = Field(default=None, ge=0)
    volume: int | None = Field(default=None, ge=0)
    option_type: str = Field(..., pattern="^(call|put)$")
    timestamp: datetime = Field(..., description="UTC timestamp of the options snapshot")
    source: str


class MarketState(BaseModel):
    """
    Unified market state object produced by one ingestion cycle.

    Primary output of Ingestion Agent; primary input to Feature Generation Agent.
    All fields must be populated before the state is passed downstream.
    """

    snapshot_time: datetime = Field(..., description="UTC time of this market snapshot")
    prices: list[RawPriceRecord] = Field(default_factory=list)
    options: list[OptionRecord] = Field(default_factory=list)
    ingestion_errors: list[str] = Field(
        default_factory=list,
        description="Non-fatal errors during this cycle (quarantined record details)",
    )
