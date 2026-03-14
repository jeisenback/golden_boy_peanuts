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

from datetime import UTC, datetime
import logging

from src.agents.feature_generation.models import FeatureSet
from src.agents.ingestion.models import OptionStructure
from src.agents.strategy_evaluation.db import write_strategy_candidates
from src.agents.strategy_evaluation.models import StrategyCandidate
from src.core.db import get_engine

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

# Phase 1 option structures generated per instrument (PRD Section 3.2; calendar spread deferred)
_PHASE_1_STRUCTURES: list[OptionStructure] = [
    OptionStructure.LONG_STRADDLE,
    OptionStructure.CALL_SPREAD,
    OptionStructure.PUT_SPREAD,
]

# Target expiration in calendar days for all Phase 1 candidates (PRD Section 10)
_DEFAULT_EXPIRATION_DAYS: int = 30

# Minimum edge score to include a candidate in results; below this = no edge (configurable)
_MIN_EDGE_SCORE: float = 0.10

# Thresholds for human-readable signal labels in the signals dict
# volatility_gap: gap > 0 → 'positive', gap < 0 → 'negative', no record → 'neutral'
# sector_dispersion: CV > HIGH → 'high', > MEDIUM → 'medium', else → 'low'
_DISPERSION_HIGH_THRESHOLD: float = 0.15  # CV > 15% = high dispersion
_DISPERSION_MEDIUM_THRESHOLD: float = 0.05  # CV > 5%  = medium dispersion


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


def _vol_gap_label(instrument: str, feature_set: FeatureSet) -> str:
    """Return human-readable volatility gap label for the signals dict.

    Args:
        instrument: Ticker symbol to look up in feature_set.volatility_gaps.
        feature_set: Current FeatureSet from Feature Generation Agent.

    Returns:
        'positive' if gap > 0, 'negative' if gap <= 0, 'neutral' if no record.
    """
    vg = next((v for v in feature_set.volatility_gaps if v.instrument == instrument), None)
    if vg is None:
        return "neutral"
    return "positive" if vg.gap > 0 else "negative"


def _dispersion_label(feature_set: FeatureSet) -> str:
    """Return human-readable sector dispersion label for the signals dict.

    Args:
        feature_set: Current FeatureSet from Feature Generation Agent.

    Returns:
        'high' if CV > _DISPERSION_HIGH_THRESHOLD, 'medium' if CV > _DISPERSION_MEDIUM_THRESHOLD,
        'low' otherwise or if sector_dispersion is None.
    """
    disp = feature_set.sector_dispersion
    if disp is None:
        return "low"
    if disp > _DISPERSION_HIGH_THRESHOLD:
        return "high"
    if disp > _DISPERSION_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def evaluate_strategies(feature_set: FeatureSet) -> list[StrategyCandidate]:
    """
    Evaluate all eligible option structures across all in-scope instruments.

    For each instrument in INSTRUMENTS_IN_SCOPE, generates one StrategyCandidate
    per Phase 1 structure (long_straddle, call_spread, put_spread). Candidates
    with edge_score below _MIN_EDGE_SCORE are filtered out. Results are sorted
    by edge_score descending and persisted to the DB (DB failures are logged and
    do not propagate — candidates are still returned to the caller).

    Args:
        feature_set: Complete FeatureSet from Feature Generation Agent.

    Returns:
        List of StrategyCandidate sorted by edge_score descending.
        Empty list if no candidates meet the minimum threshold.
    """
    generated_at = datetime.now(tz=UTC)
    candidates: list[StrategyCandidate] = []

    for instrument in INSTRUMENTS_IN_SCOPE:
        edge_score = compute_edge_score(instrument, feature_set)
        if edge_score < _MIN_EDGE_SCORE:
            continue

        signals: dict[str, str] = {
            "volatility_gap": _vol_gap_label(instrument, feature_set),
            "sector_dispersion": _dispersion_label(feature_set),
        }

        for structure in _PHASE_1_STRUCTURES:
            candidates.append(
                StrategyCandidate(
                    instrument=instrument,
                    structure=structure,
                    expiration=_DEFAULT_EXPIRATION_DAYS,
                    edge_score=edge_score,
                    signals=signals,
                    generated_at=generated_at,
                )
            )

    candidates.sort(key=lambda c: c.edge_score, reverse=True)

    # Persist to DB — failures are logged but do not propagate (degraded-mode).
    # This mirrors the run_ingestion() pattern: a DB outage must not suppress
    # the candidate list from the caller. Candidates are always returned.
    if candidates:
        try:
            engine = get_engine()
            write_strategy_candidates(candidates, engine)
        except Exception as exc:
            logger.warning("Failed to persist strategy candidates: %s", exc)

    return candidates
