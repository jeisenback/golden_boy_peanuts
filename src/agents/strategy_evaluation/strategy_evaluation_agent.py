"""
Strategy Evaluation Agent

Responsibilities (Design Doc Section 4, PRD Section 4.4):
  - Evaluate long straddle, call spread, put spread, calendar spread
    structures based on signals from FeatureSet
  - Compute a composite edge_score in [0.0, 1.0] per candidate
  - Rank candidates by edge_score descending
  - Attach contributing signal references for explainability
  - Output StrategyCandidate list matching PRD Section 9 schema
  - Persist candidates to PostgreSQL

ESOD constraints: Python 3.11+, type hints on all public functions,
no langchain.*/langgraph.* imports, static scoring rules only in Phase 1
(ML-based weighting deferred per ESOD Section 8).
"""
from __future__ import annotations

import logging

from src.agents.feature_generation.models import FeatureSet
from src.agents.strategy_evaluation.models import StrategyCandidate

logger = logging.getLogger(__name__)

# Instruments in scope for Phase 1 (PRD Section 3.1)
INSTRUMENTS_IN_SCOPE: list[str] = ["USO", "XLE", "XOM", "CVX", "CL=F", "BZ=F"]


def compute_edge_score(instrument: str, feature_set: FeatureSet) -> float:
    """
    Compute a composite edge score for a given instrument from the FeatureSet.

    Scoring is static/heuristic for Phase 1 MVP.
    ML-based dynamic weighting is explicitly deferred (ESOD Section 8).

    Args:
        instrument: Ticker symbol of the instrument to evaluate.
        feature_set: Computed signals from Feature Generation Agent.

    Returns:
        Float in [0.0, 1.0]. Higher = stronger signal confluence.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "compute_edge_score not yet implemented. "
        "TODO: Heuristic scoring combining volatility_gap, supply_shock_probability, "
        "narrative_velocity. Edge score = weighted sum of normalized signal values."
    )


def evaluate_strategies(feature_set: FeatureSet) -> list[StrategyCandidate]:
    """
    Evaluate all eligible option structures across all in-scope instruments.

    Args:
        feature_set: Complete FeatureSet from Feature Generation Agent.

    Returns:
        List of StrategyCandidate sorted by edge_score descending.
        Empty list if no candidates meet the minimum threshold.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "evaluate_strategies not yet implemented. "
        "TODO: Iterate INSTRUMENTS_IN_SCOPE. For each, call compute_edge_score. "
        "Generate StrategyCandidate for each structure. Sort by edge_score DESC."
    )
