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
from src.agents.ingestion.models import MarketState, OptionStructure
from src.agents.strategy_evaluation.db import write_strategy_candidates
from src.agents.strategy_evaluation.models import StrategyCandidate
from src.core.bsm import BSMGreeks, greeks_for_strategy
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

# Thresholds for supply shock probability labels
_SUPPLY_SHOCK_HIGH_THRESHOLD: float = 0.60  # probability > 60% = high
_SUPPLY_SHOCK_MEDIUM_THRESHOLD: float = 0.30  # probability > 30% = medium

# Phase 2 multiplier weights for supply shock and futures curve steepness
_SUPPLY_SHOCK_WEIGHT: float = 0.30
_CURVE_STEEPNESS_WEIGHT: float = 0.15


def compute_edge_score(
    instrument: str,
    feature_set: FeatureSet,
    supply_shock_probability: float | None = None,
    futures_curve_steepness: float | None = None,
) -> float:
    """
    Compute a composite edge score for a given instrument from the FeatureSet.

    Phase 1 base score: weighted sum of volatility gap and sector dispersion.
    Phase 2 multipliers: supply shock probability and futures curve steepness
    amplify the base score when present.

    Formula:
        base = vol_gap_norm * _VOL_GAP_WEIGHT + disp_norm * _DISPERSION_WEIGHT
        score = base * (1 + _SUPPLY_SHOCK_WEIGHT * supply_shock)
              * (1 + _CURVE_STEEPNESS_WEIGHT * |curve_steepness|)
        return min(score, 1.0)

    When supply_shock_probability or futures_curve_steepness is None, the
    corresponding multiplier is 1.0 (no effect), preserving Phase 1 behavior.

    Args:
        instrument: Ticker symbol of the instrument to evaluate.
        feature_set: Computed signals from Feature Generation Agent.
        supply_shock_probability: Float in [0.0, 1.0], or None if unavailable.
            Pydantic validation on FeatureSet.supply_shock_probability enforces range.
        futures_curve_steepness: Unbounded float (WTI futures curve slope; contango > 0).
            None if unavailable.

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

    base_score = vol_gap_contribution + disp_contribution

    # --- Phase 2 multipliers ---
    shock_multiplier = 1.0 + _SUPPLY_SHOCK_WEIGHT * (supply_shock_probability or 0.0)
    curve_multiplier = 1.0 + _CURVE_STEEPNESS_WEIGHT * abs(futures_curve_steepness or 0.0)

    return min(base_score * shock_multiplier * curve_multiplier, 1.0)


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


# ---------------------------------------------------------------------------
# BSM Greeks attachment (Phase 3 options platform addition)
#
# Minimum liquidity thresholds — candidates below these thresholds get
# liquidity_ok=False in their signals dict and no BSM Greeks attached.
# ---------------------------------------------------------------------------
_MIN_OPTION_VOLUME: int = 10
_MIN_OPTION_OPEN_INTEREST: int = 50


def _resolve_atm_greeks(
    instrument: str,
    structure: OptionStructure,
    market_state: MarketState,
) -> BSMGreeks | None:
    """Resolve BSM Greeks for the ATM option of *instrument* in *market_state*.

    Finds the current spot price and ATM implied volatility from the options
    chain, then delegates to greeks_for_strategy(). Returns None (with a DEBUG
    log) if any required input is missing or greeks_for_strategy returns None.

    Liquidity guard: skips options whose volume < _MIN_OPTION_VOLUME or whose
    open_interest < _MIN_OPTION_OPEN_INTEREST — treats them as illiquid and
    returns None.

    Args:
        instrument: Instrument ticker to look up in market_state.
        structure: Option structure to compute Greeks for.
        market_state: Current MarketState containing prices and options chain.

    Returns:
        BSMGreeks for the structure, or None if computation is not possible.
    """
    # --- Spot price ---
    spot_record = next(
        (r for r in market_state.prices if r.instrument == instrument),
        None,
    )
    if spot_record is None:
        logger.debug("No spot price for %s in market_state — skipping BSM", instrument)
        return None

    spot = spot_record.price

    # --- ATM option: nearest expiry, closest strike ---
    opts = [o for o in market_state.options if o.instrument == instrument]
    if not opts:
        logger.debug("No options chain for %s in market_state — skipping BSM", instrument)
        return None

    nearest_expiry = min(o.expiration_date for o in opts)
    expiry_opts = [o for o in opts if o.expiration_date == nearest_expiry]
    atm_opt = min(expiry_opts, key=lambda o: abs(o.strike - spot))

    if atm_opt.implied_volatility is None:
        logger.debug(
            "ATM option for %s has no IV (strike=%.2f) — skipping BSM",
            instrument,
            atm_opt.strike,
        )
        return None

    # --- Liquidity guard ---
    vol_ok = atm_opt.volume is None or atm_opt.volume >= _MIN_OPTION_VOLUME
    oi_ok = atm_opt.open_interest is None or atm_opt.open_interest >= _MIN_OPTION_OPEN_INTEREST
    if not vol_ok or not oi_ok:
        logger.debug(
            "ATM option for %s is illiquid (volume=%s, oi=%s) — skipping BSM",
            instrument,
            atm_opt.volume,
            atm_opt.open_interest,
        )
        return None

    # --- Time-to-expiry in years ---
    from datetime import UTC as _UTC  # noqa: PLC0415,RUF100 — local import avoids circular risk

    now = datetime.now(tz=_UTC)
    days_to_expiry = (atm_opt.expiration_date - now).total_seconds() / 86_400.0
    tte_years = days_to_expiry / 365.0

    return greeks_for_strategy(
        spot=spot,
        strike_atm=atm_opt.strike,
        time_to_expiry_years=tte_years,
        implied_vol=atm_opt.implied_volatility,
        structure=structure.value,
    )


def evaluate_strategies(
    feature_set: FeatureSet,
    market_state: MarketState | None = None,
) -> list[StrategyCandidate]:
    """
    Evaluate all eligible option structures across all in-scope instruments.

    For each instrument in INSTRUMENTS_IN_SCOPE, generates one StrategyCandidate
    per Phase 1 structure (long_straddle, call_spread, put_spread). Candidates
    with edge_score below _MIN_EDGE_SCORE are filtered out. Results are sorted
    by edge_score descending and persisted to the DB (DB failures are logged and
    do not propagate — candidates are still returned to the caller).

    BSM Greeks (Phase 3 options platform):
        When market_state is provided, BSM Greeks are computed and attached to
        each candidate via _resolve_atm_greeks(). The signals dict gains a
        'liquidity_ok' key ('true'/'false') reflecting whether the ATM option
        meets _MIN_OPTION_VOLUME and _MIN_OPTION_OPEN_INTEREST thresholds.
        If BSM computation fails for any reason, candidate.greeks stays None
        and processing continues — BSM is strictly additive.

    Args:
        feature_set: Complete FeatureSet from Feature Generation Agent.
        market_state: Optional live market snapshot. When provided, BSM Greeks
            are attached to each candidate and liquidity_ok is set in signals.

    Returns:
        List of StrategyCandidate sorted by edge_score descending.
        Empty list if no candidates meet the minimum threshold.
    """
    generated_at = datetime.now(tz=UTC)
    candidates: list[StrategyCandidate] = []

    for instrument in INSTRUMENTS_IN_SCOPE:
        edge_score = compute_edge_score(
            instrument,
            feature_set,
            supply_shock_probability=feature_set.supply_shock_probability,
            futures_curve_steepness=feature_set.futures_curve_steepness,
        )
        if edge_score < _MIN_EDGE_SCORE:
            continue

        signals: dict[str, str] = {
            "volatility_gap": _vol_gap_label(instrument, feature_set),
            "sector_dispersion": _dispersion_label(feature_set),
            "supply_shock_probability": _supply_shock_label(feature_set),
            "futures_curve_steepness": _curve_steepness_label(feature_set),
        }

        for structure in _PHASE_1_STRUCTURES:
            greeks: BSMGreeks | None = None

            if market_state is not None:
                try:
                    greeks = _resolve_atm_greeks(instrument, structure, market_state)
                except Exception as exc:
                    logger.debug("BSM computation failed for %s/%s: %s", instrument, structure, exc)

                # Add liquidity_ok to signals dict (requires market_state)
                candidate_opts = [
                    o for o in market_state.options if o.instrument == instrument
                ]
                if candidate_opts:
                    nearest_exp = min(o.expiration_date for o in candidate_opts)
                    exp_opts = [o for o in candidate_opts if o.expiration_date == nearest_exp]
                    spot_rec = next(
                        (r for r in market_state.prices if r.instrument == instrument), None
                    )
                    if spot_rec is not None:
                        atm = min(exp_opts, key=lambda o: abs(o.strike - spot_rec.price))
                        vol_ok = atm.volume is None or atm.volume >= _MIN_OPTION_VOLUME
                        oi_ok = (
                            atm.open_interest is None
                            or atm.open_interest >= _MIN_OPTION_OPEN_INTEREST
                        )
                        signals = {**signals, "liquidity_ok": str(vol_ok and oi_ok).lower()}

            candidates.append(
                StrategyCandidate(
                    instrument=instrument,
                    structure=structure,
                    expiration=_DEFAULT_EXPIRATION_DAYS,
                    edge_score=edge_score,
                    signals=signals,
                    generated_at=generated_at,
                    greeks=greeks,
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
