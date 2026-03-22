"""
Pydantic models for the Alternative Data Agent (Phase 3).

All external feed data must be validated through these models before
any downstream processing (ESOD Section 6).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from src.core.compat import StrEnum


class TradeType(StrEnum):
    """Supported insider trade types (matches insider_trades.trade_type CHECK constraint)."""

    BUY = "buy"
    SELL = "sell"
    GRANT = "grant"
    EXERCISE = "exercise"


class QuiverInsiderRow(BaseModel):
    """
    Raw row from Quiver Quantitative ``/beta/live/insiders/{ticker}`` API.

    All fields are optional — the Pydantic boundary validates the shape before
    any field access in ``_parse_quiver_row`` (ESOD §6).
    """

    Transaction: str | None = None
    Date: str | None = None
    Name: str | None = None
    Shares: float | None = None  # API may return float; cast to int downstream
    Price: float | None = None


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
