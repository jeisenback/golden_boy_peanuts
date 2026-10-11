"""
Strategy Evaluation Agent

Responsibilities (Design Doc Section 4, PRD Section 4.4):
  - Evaluate call spread and put spread structures for the tradeable
    instruments (USO, XLE, XOM, CVX) from the FeatureSet; long straddles are
    no longer emitted and calendar spreads are deferred (issue #134)
  - Compute a directional edge_score in [0.0, 1.0] per candidate from a signed
    direction net (curve, supply shock, tanker, insider), amplified by sector
    dispersion and narrative velocity; the volatility gap does not score
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

# Tradeable targets: the only instruments that receive strategy candidates. Historical
# options data exists for these (vendor evaluation #170), so outcomes can be scored.
TRADEABLE_INSTRUMENTS: list[str] = ["USO", "XLE", "XOM", "CVX"]

# Signal sources: WTI and Brent futures feed every signal (prices, OVX, curve steepness,
# supply events) but have no scoreable options history, so no candidates are emitted (#219).
SIGNAL_ONLY_INSTRUMENTS: list[str] = ["CL=F", "BZ=F"]

# Full universe for ingestion and feature generation (PRD Section 3.1).
INSTRUMENTS_IN_SCOPE: list[str] = TRADEABLE_INSTRUMENTS + SIGNAL_ONLY_INSTRUMENTS

# Option structures emitted per instrument (PRD Section 3.2). Long straddles are dropped:
# the USO study found buying volatility loses to premium (#134); calendar spread deferred.
_PHASE_1_STRUCTURES: list[OptionStructure] = [
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

# Thresholds for supply shock probability labels
_SUPPLY_SHOCK_HIGH_THRESHOLD: float = 0.60  # probability > 60% = high
_SUPPLY_SHOCK_MEDIUM_THRESHOLD: float = 0.30  # probability > 30% = medium


# ---------------------------------------------------------------------------
# Direction signals (issue #134, docs/plans/structure-selection-spec.md)
#
# Each signal maps to a score in [-1, 1] where positive means bullish crude, and
# direction_net is their weighted sum (a missing signal contributes 0.0). The weights
# are static heuristics, unvalidated until the forward test measures them.
#
# futures_curve_steepness is (second_month - front_month) / front_month, so a one-month
# spread of 5% of the front price maps to full strength. This is set from the signal's
# units, not from observed data; recheck against the first nightly snapshots.
#
# _W_CURVE is 0.0 (issue #240): a 1986-2024 backtest of the curve against 30-day forward
# WTI spot returns found the opposite of the backwardation-bullish mapping (deep contango
# preceded stronger returns, significantly; deep backwardation preceded weaker returns, not
# significantly). The mapping and the other weights are kept, and the curve is still
# reported in `signals`, so the forward test can validate or flip it. Do not set a
# non-zero weight without evidence.
# ---------------------------------------------------------------------------
_CURVE_FULL: float = 0.05
_W_CURVE: float = 0.0
_W_SUPPLY: float = 0.35
_W_TANKER: float = 0.25
_W_INSIDER: float = 0.15

# Amplifier: magnitude-only signals scale the net but never set its direction.
_W_DISPERSION: float = 0.30
_W_NARRATIVE: float = 0.10

# Insider filings exist only for the equities; USO and XLE are ETFs with no insiders.
_INSIDER_COVERED: frozenset[str] = frozenset({"XOM", "CVX"})


def compute_direction_net(
    instrument: str,
    *,
    supply_shock_probability: float | None,
    futures_curve_steepness: float | None,
    insider_conviction_score: float | None,
    tanker_disruption_index: float | None,
) -> float:
    """
    Combine the direction signals into one signed net for an instrument.

    Args:
        instrument: Ticker; insider conviction counts only for XOM and CVX.
        supply_shock_probability: [0.0, 1.0], bullish only; None contributes 0.0.
        futures_curve_steepness: Signed; backwardation (negative) is bullish and
            contango (positive) is bearish, clipped at +/- _CURVE_FULL. Carries weight
            _W_CURVE, currently 0.0, so it does not move the net (issue #240).
        insider_conviction_score: [0.0, 1.0] with 0.5 neutral; above is bullish.
        tanker_disruption_index: [0.0, 1.0], bullish only.

    Returns:
        Float in [-1.0, 1.0]; positive means bullish crude, 0.0 means no view. With the
        curve weight at 0.0 the practical range is [-0.75, 0.75].
    """
    curve = 0.0
    if futures_curve_steepness is not None:
        curve = min(max(-futures_curve_steepness / _CURVE_FULL, -1.0), 1.0)

    insider = 0.0
    if insider_conviction_score is not None and instrument in _INSIDER_COVERED:
        insider = 2.0 * insider_conviction_score - 1.0

    return (
        _W_CURVE * curve
        + _W_SUPPLY * (supply_shock_probability or 0.0)
        + _W_TANKER * (tanker_disruption_index or 0.0)
        + _W_INSIDER * insider
    )


def compute_edge_score(
    instrument: str,
    feature_set: FeatureSet,
    option_structure: OptionStructure,
    supply_shock_probability: float | None = None,
    futures_curve_steepness: float | None = None,
    insider_conviction_score: float | None = None,
    narrative_velocity: float | None = None,
    tanker_disruption_index: float | None = None,
) -> float:
    """
    Compute the edge score of one directional spread for an instrument.

    The direction net (see compute_direction_net) is the score for a call spread when
    positive and for a put spread when negative; the other side scores 0.0. Sector
    dispersion and narrative velocity then amplify it:

        amplifier = 1 + _W_DISPERSION * sector_dispersion
                      + _W_NARRATIVE * min(narrative_velocity, 1.0)
        score     = min(1.0, side_net * amplifier)

    The volatility gap carries no weight: the USO study found it does not predict
    which days buying volatility pays (docs/backtest_reports/217-ovx-gap-ratio-USO.md).

    Args:
        instrument: Ticker symbol of the instrument to evaluate.
        feature_set: Supplies sector_dispersion for the amplifier.
        option_structure: CALL_SPREAD or PUT_SPREAD.
        supply_shock_probability: [0.0, 1.0], or None if unavailable.
        futures_curve_steepness: Signed (second - front) / front; positive is contango.
        insider_conviction_score: [0.0, 1.0] with 0.5 neutral, or None. XOM and CVX only.
        narrative_velocity: Non-negative headline acceleration, or None.
        tanker_disruption_index: [0.0, 1.0], or None.

    Returns:
        Float in [0.0, 1.0]; 0.0 when the signals point the other way or are absent.

    Raises:
        ValueError: if option_structure is not CALL_SPREAD or PUT_SPREAD.
    """
    if option_structure not in (OptionStructure.CALL_SPREAD, OptionStructure.PUT_SPREAD):
        raise ValueError(
            f"Directional scoring supports call and put spreads, got {option_structure}"
        )

    net = compute_direction_net(
        instrument,
        supply_shock_probability=supply_shock_probability,
        futures_curve_steepness=futures_curve_steepness,
        insider_conviction_score=insider_conviction_score,
        tanker_disruption_index=tanker_disruption_index,
    )
    side_net = net if option_structure is OptionStructure.CALL_SPREAD else -net
    if side_net <= 0.0:
        return 0.0

    dispersion = feature_set.sector_dispersion or 0.0
    amplifier = (
        1.0 + _W_DISPERSION * dispersion + _W_NARRATIVE * min(narrative_velocity or 0.0, 1.0)
    )
    return min(side_net * amplifier, 1.0)


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


def _supply_shock_label(feature_set: FeatureSet) -> str:
    """Return human-readable supply shock probability label.

    Args:
        feature_set: Current FeatureSet from Feature Generation Agent.

    Returns:
        'high' if probability > _SUPPLY_SHOCK_HIGH_THRESHOLD,
        'medium' if > _SUPPLY_SHOCK_MEDIUM_THRESHOLD, 'low' if > 0, 'none' if None or 0.
    """
    prob = feature_set.supply_shock_probability
    if prob is None or prob == 0.0:
        return "none"
    if prob > _SUPPLY_SHOCK_HIGH_THRESHOLD:
        return "high"
    if prob > _SUPPLY_SHOCK_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def _curve_steepness_label(feature_set: FeatureSet) -> str:
    """Return human-readable futures curve steepness label.

    Args:
        feature_set: Current FeatureSet from Feature Generation Agent.

    Returns:
        'contango' if steepness > 0, 'backwardation' if < 0, 'flat' if None or 0.
    """
    steep = feature_set.futures_curve_steepness
    if steep is None or steep == 0.0:
        return "flat"
    return "contango" if steep > 0 else "backwardation"


def evaluate_strategies(feature_set: FeatureSet) -> list[StrategyCandidate]:
    """
    Evaluate call and put spreads for each tradeable instrument.

    For each instrument in TRADEABLE_INSTRUMENTS (USO, XLE, XOM, CVX), scores a call
    spread and a put spread with compute_edge_score(). Because the two are opposite
    bets, only the side the direction signals favor can clear _MIN_EDGE_SCORE, so a run
    emits at most one candidate per instrument, and none when the signals cancel or are
    absent. Long straddles are not emitted. Results are sorted by edge_score descending
    and persisted to the DB (DB failures are logged and do not propagate; candidates
    are still returned to the caller).

    Args:
        feature_set: Complete FeatureSet from Feature Generation Agent.

    Returns:
        List of StrategyCandidate sorted by edge_score descending, each with a
        signals["direction"] of "bullish" (call spread) or "bearish" (put spread).
        Empty list if no candidate meets the minimum threshold.
    """
    generated_at = datetime.now(tz=UTC)
    candidates: list[StrategyCandidate] = []

    for instrument in TRADEABLE_INSTRUMENTS:
        labels: dict[str, str] = {
            "volatility_gap": _vol_gap_label(instrument, feature_set),
            "sector_dispersion": _dispersion_label(feature_set),
            "supply_shock_probability": _supply_shock_label(feature_set),
            "futures_curve_steepness": _curve_steepness_label(feature_set),
        }
        for structure in _PHASE_1_STRUCTURES:
            edge_score = compute_edge_score(
                instrument,
                feature_set,
                structure,
                supply_shock_probability=feature_set.supply_shock_probability,
                futures_curve_steepness=feature_set.futures_curve_steepness,
                insider_conviction_score=feature_set.insider_conviction_score,
                narrative_velocity=feature_set.narrative_velocity,
                tanker_disruption_index=feature_set.tanker_disruption_index,
            )
            if edge_score < _MIN_EDGE_SCORE:
                continue
            direction = "bullish" if structure is OptionStructure.CALL_SPREAD else "bearish"
            candidates.append(
                StrategyCandidate(
                    instrument=instrument,
                    structure=structure,
                    expiration=_DEFAULT_EXPIRATION_DAYS,
                    edge_score=edge_score,
                    signals={**labels, "direction": direction},
                    generated_at=generated_at,
                )
            )

    if not candidates:
        # A quiet market and a broken input look the same in the output, so say why.
        nets = {
            instrument: round(
                compute_direction_net(
                    instrument,
                    supply_shock_probability=feature_set.supply_shock_probability,
                    futures_curve_steepness=feature_set.futures_curve_steepness,
                    insider_conviction_score=feature_set.insider_conviction_score,
                    tanker_disruption_index=feature_set.tanker_disruption_index,
                ),
                4,
            )
            for instrument in TRADEABLE_INSTRUMENTS
        }
        logger.info(
            "No directional candidates: supply_shock=%s curve=%s tanker=%s insider=%s "
            "direction_net=%s (a net must reach %.2f in either direction)",
            feature_set.supply_shock_probability,
            feature_set.futures_curve_steepness,
            feature_set.tanker_disruption_index,
            feature_set.insider_conviction_score,
            nets,
            _MIN_EDGE_SCORE,
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
