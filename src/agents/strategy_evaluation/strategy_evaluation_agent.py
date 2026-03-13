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

# ---------------------------------------------------------------------------
# Phase 1 edge score formula — static heuristic weights
#
# Two signals are available in Phase 1:
#   1. volatility_gap  — IV premium over realized vol for the instrument
#   2. sector_dispersion — price spread across XOM, CVX, USO, XLE
#
# Normalization:
#   vol_gap_norm  = clip(gap / _VOL_GAP_FULL_WEIGHT, 0.0, 1.0)
#                   A 20% IV premium (gap = 0.20) maps to 1.0; larger gaps cap at 1.0.
#   disp_norm     = sector_dispersion (already in [0.0, 1.0] from compute_sector_dispersion)
#
# Weighted sum:
#   edge_score = vol_gap_norm x _VOL_GAP_WEIGHT + disp_norm x _DISPERSION_WEIGHT
#
# If a signal is None (not computed), it contributes 0.0 — not an error.
#
# Phase 1 heuristic — weights to be tuned in Phase 3 via ML.
# ---------------------------------------------------------------------------
_VOL_GAP_FULL_WEIGHT: float = 0.20  # gap value that maps to full (1.0) contribution
_VOL_GAP_WEIGHT: float = 0.70  # volatility gap share of total score
_DISPERSION_WEIGHT: float = 0.30  # sector dispersion share of total score


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
        Returns 0.0 if the instrument has no volatility_gap record in the FeatureSet.
    """
    # --- Volatility gap contribution ---
    vol_gap_record = next(
        (vg for vg in feature_set.volatility_gaps if vg.instrument == instrument),
        None,
    )
    if vol_gap_record is None:
        return 0.0

    vol_gap_norm = min(max(vol_gap_record.gap / _VOL_GAP_FULL_WEIGHT, 0.0), 1.0)
    vol_gap_contribution = vol_gap_norm * _VOL_GAP_WEIGHT

    # --- Sector dispersion contribution ---
    disp_norm = feature_set.sector_dispersion if feature_set.sector_dispersion is not None else 0.0
    disp_contribution = disp_norm * _DISPERSION_WEIGHT

    return vol_gap_contribution + disp_contribution


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
