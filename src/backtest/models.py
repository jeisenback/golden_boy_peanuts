"""
Pydantic boundary models for the backtesting pipeline.

These models are isolated from the live pipeline models (StrategyCandidate,
FeatureSet, etc.) to ensure historical replay data never pollutes production
tables or reporting queries.

Data flow:
    HistoricalLoader → HistoricalSlice
    run_backtest_pipeline → BacktestCandidate (written via write_backtest_candidate)
    OutcomeTracker → BacktestOutcome (written via record_outcome)
    BacktestReport → reads from DB, produces matplotlib chart
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from pydantic import BaseModel, Field


class BacktestCandidate(BaseModel):
    """
    A strategy candidate produced during backtesting replay.

    Written to backtest_candidates by write_backtest_candidate().
    id is assigned by the database (gen_random_uuid()); it is None until
    the row is persisted.
    """

    id: uuid.UUID | None = None
    instrument: str
    structure: str  # 'long_straddle' | 'call_spread' | 'put_spread'
    snapshot_time: datetime  # Point-in-time of the historical slice
    edge_score: float = Field(ge=0.0, le=1.0)
    signals: dict[str, Any]
    generated_at: datetime


class BacktestOutcome(BaseModel):
    """
    The resolved P&L outcome for a BacktestCandidate at expiration.

    Written to backtest_outcomes by record_outcome().
    profitable=None means yfinance returned no data; row is still inserted.
    entry_premium/upper_strike/lower_strike are nullable — None for long_straddle,
    populated for spreads (deferred to Sprint A follow-up).
    """

    id: uuid.UUID | None = None
    candidate_id: uuid.UUID
    structure: str
    expiration: datetime
    underlying_close: float
    entry_premium: float | None = None
    upper_strike: float | None = None
    lower_strike: float | None = None
    profitable: bool | None = None  # None = could not be determined
    recorded_at: datetime | None = None
