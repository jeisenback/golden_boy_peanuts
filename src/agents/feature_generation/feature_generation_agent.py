"""
Feature Generation Agent

Responsibilities (Design Doc Section 4, PRD Section 4.3):
  - Compute volatility gaps (realized vs. implied)
  - Compute futures curve steepness (WTI forward curve)
  - Compute sector dispersion across XOM, CVX, USO, XLE
  - Compute insider conviction scores from EDGAR data
  - Compute narrative velocity / headline acceleration
  - Compute supply shock probability from event scores
  - Persist FeatureSet to PostgreSQL for Strategy Evaluation Agent

ESOD constraints: Python 3.11+, type hints on all public functions,
no langchain.*/langgraph.* imports.
"""

from __future__ import annotations

import logging

from src.agents.event_detection.models import DetectedEvent
from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.ingestion.models import MarketState

logger = logging.getLogger(__name__)


def compute_volatility_gap(market_state: MarketState) -> list[VolatilityGap]:
    """
    Compute realized vs. implied volatility gaps for all instruments with options data.

    Args:
        market_state: Current validated market snapshot from Ingestion Agent.

    Returns:
        List of VolatilityGap objects, one per instrument with options data.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "compute_volatility_gap not yet implemented. "
        "TODO: Calculate realized vol from price history in DB. "
        "Compare to implied_volatility from options chain."
    )


def compute_supply_shock_probability(events: list[DetectedEvent]) -> float:
    """
    Estimate supply shock probability based on detected events.

    Args:
        events: DetectedEvent objects from Event Detection Agent.

    Returns:
        Float in [0.0, 1.0] representing supply shock probability.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "compute_supply_shock_probability not yet implemented. "
        "TODO: Aggregate confidence_score and intensity of supply-type events."
    )


def run_feature_generation(
    market_state: MarketState,
    events: list[DetectedEvent],
) -> FeatureSet:
    """
    Compute the full FeatureSet for one evaluation cycle.

    Args:
        market_state: Current validated market snapshot.
        events: Detected events from Event Detection Agent.

    Returns:
        FeatureSet with all computed signals.
        feature_errors contains details of any computation failures.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "run_feature_generation not yet implemented. "
        "TODO: Orchestrate all compute_* functions. "
        "Catch individual signal failures and continue with partial FeatureSet."
    )
