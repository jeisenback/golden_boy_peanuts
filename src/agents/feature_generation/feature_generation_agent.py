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

from datetime import UTC, datetime
import logging
import math
import statistics

from src.agents.event_detection.models import DetectedEvent
from src.agents.feature_generation.db import read_price_history, write_feature_set
from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.ingestion.models import MarketState, OptionRecord
from src.core.db import get_engine

logger = logging.getLogger(__name__)

# Annualization factor for daily log-return stdev (US equity trading days per year)
_TRADING_DAYS_PER_YEAR: int = 252

# Minimum number of DB price records required to compute realized volatility
_MIN_PRICE_RECORDS: int = 10

# Instruments whose prices constitute the 'sector' for dispersion measurement
_SECTOR_INSTRUMENTS: frozenset[str] = frozenset({"XOM", "CVX", "USO", "XLE"})

# Minimum number of sector instruments required to compute dispersion
_MIN_SECTOR_INSTRUMENTS: int = 2

# Maximum value returned by compute_sector_dispersion (CV capped for model input)
_CV_CAP: float = 1.0

# Guard: mean sector price must exceed this before CV division is safe
_MEAN_PRICE_ZERO: float = 0.0

# Intensity weights for supply shock probability estimation
_INTENSITY_WEIGHT_LOW: float = 0.33
_INTENSITY_WEIGHT_MEDIUM: float = 0.66
_INTENSITY_WEIGHT_HIGH: float = 1.0


def compute_volatility_gap(market_state: MarketState) -> list[VolatilityGap]:
    """
    Compute realized vs. implied volatility gaps for all instruments.

    For each instrument in market_state.prices:
    - Fetches the last 30 daily price records from the DB to compute realized vol.
    - Selects the ATM (at-the-money) implied vol from the nearest expiry in
      market_state.options, using the option whose strike is closest to the
      current price.
    - Skips any instrument that lacks options data or sufficient price history,
      logging a WARNING for each skip (not an error).

    Realized volatility formula:
        stdev(log(P_t / P_{t-1})) x sqrt(252)

    Args:
        market_state: Current validated market snapshot from Ingestion Agent.

    Returns:
        List of VolatilityGap objects, one per instrument with sufficient data.
        ingestion_errors is the ESOD-4 structured error response on the caller's
        FeatureSet; per-instrument skips here produce WARNING logs only.

    Raises:
        Exception: Propagates DB engine acquisition failures to the caller
            (run_feature_generation handles degraded-mode behavior).
    """
    _engine = get_engine()
    computed_at = datetime.now(UTC)
    result: list[VolatilityGap] = []

    # Build current price index: instrument → latest price
    current_prices: dict[str, float] = {r.instrument: r.price for r in market_state.prices}

    # Build options index: instrument → list of OptionRecords
    options_by_instrument: dict[str, list[OptionRecord]] = {}
    for opt in market_state.options:
        options_by_instrument.setdefault(opt.instrument, []).append(opt)

    for instrument, current_price in current_prices.items():
        # --- Guard: options availability ---
        opts = options_by_instrument.get(instrument)
        if not opts:
            logger.warning(
                "No options data for %s — skipping volatility gap computation", instrument
            )
            continue

        # --- Guard: price history ---
        prices = read_price_history(instrument, _engine)
        if len(prices) < _MIN_PRICE_RECORDS:
            logger.warning(
                "Insufficient price history for %s: %d record(s) (min %d) — skipping",
                instrument,
                len(prices),
                _MIN_PRICE_RECORDS,
            )
            continue

        # --- Realized volatility: annualized stdev of daily log returns ---
        log_returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
        realized_vol = statistics.stdev(log_returns) * math.sqrt(_TRADING_DAYS_PER_YEAR)

        # --- ATM implied vol: nearest expiry, closest strike ---
        nearest_expiry = min(o.expiration_date for o in opts)
        expiry_opts = [o for o in opts if o.expiration_date == nearest_expiry]
        atm_opt = min(expiry_opts, key=lambda o: abs(o.strike - current_price))

        if atm_opt.implied_volatility is None:
            logger.warning(
                "ATM option for %s (strike=%.2f) has no implied volatility — skipping",
                instrument,
                atm_opt.strike,
            )
            continue

        implied_vol = atm_opt.implied_volatility
        result.append(
            VolatilityGap(
                instrument=instrument,
                realized_vol=realized_vol,
                implied_vol=implied_vol,
                gap=implied_vol - realized_vol,
                computed_at=computed_at,
            )
        )

    return result


def compute_sector_dispersion(market_state: MarketState) -> float | None:
    """
    Compute price dispersion across the equity/ETF sector instruments.

    Measures how much XOM, CVX, USO, and XLE prices diverge from each other
    using the coefficient of variation (CV = stddev / mean).  High dispersion
    alongside a positive volatility gap strengthens the edge score for equity
    options (PRD Section 4.3).

    The `_MIN_SECTOR_INSTRUMENTS = 2` guard guarantees that `statistics.stdev`
    always receives at least 2 values; `StatisticsError` is therefore not an
    expected exception path.

    Args:
        market_state: Current validated market snapshot from Ingestion Agent.

    Returns:
        CV capped to [0.0, 1.0], or None if fewer than 2 sector instruments
        are present in market_state.prices (WARNING logged).
    """
    relevant_prices = [r.price for r in market_state.prices if r.instrument in _SECTOR_INSTRUMENTS]

    if len(relevant_prices) < _MIN_SECTOR_INSTRUMENTS:
        logger.warning(
            "Insufficient sector instruments for dispersion: %d present (min %d) — returning None",
            len(relevant_prices),
            _MIN_SECTOR_INSTRUMENTS,
        )
        return None

    mean_price = statistics.mean(relevant_prices)
    if mean_price == _MEAN_PRICE_ZERO:
        logger.warning("Mean sector price is zero — cannot compute CV; returning None")
        return None

    cv = statistics.stdev(relevant_prices) / mean_price
    return min(cv, _CV_CAP)


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
    # Phase 1 lightweight heuristic:
    # - Consider events that are supply-related (EventType values indicating
    #   supply disruption, refinery outage, or tanker chokepoint, plus sanctions)
    # - Map intensity to a numeric weight and treat confidence_score as an
    #   independent probability that the event represents a true supply shock.
    # - Combine multiple events by computing the probability that at least one
    #   of the supply events materializes: 1 - prod(1 - p_i).
    if not events:
        return 0.0

    from src.agents.event_detection.models import (
        EventIntensity,
        EventType,
    )

    # Intensity weights (low, medium, high)
    intensity_weight = {
        EventIntensity.LOW: _INTENSITY_WEIGHT_LOW,
        EventIntensity.MEDIUM: _INTENSITY_WEIGHT_MEDIUM,
        EventIntensity.HIGH: _INTENSITY_WEIGHT_HIGH,
    }

    # Supply-related event types to consider
    supply_types = {
        EventType.SUPPLY_DISRUPTION,
        EventType.REFINERY_OUTAGE,
        EventType.TANKER_CHOKEPOINT,
        EventType.SANCTIONS,
    }

    probs: list[float] = []
    for ev in events:
        if ev.event_type in supply_types:
            weight = intensity_weight.get(ev.intensity, 0.0)
            p = max(0.0, min(1.0, ev.confidence_score * weight))
            probs.append(p)

    if not probs:
        return 0.0

    # Combine independent-event probabilities into a single probability that
    # at least one supply shock occurs (1 - product(1 - p_i)).
    prod = 1.0
    for p in probs:
        prod *= 1.0 - p

    result = 1.0 - prod
    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, result))


def run_feature_generation(
    market_state: MarketState,
    events: list[DetectedEvent],
) -> FeatureSet:
    """
    Compute the full FeatureSet for one evaluation cycle.

    Calls each compute_* function independently. If a signal fails, the error
    is appended to feature_errors and processing continues — the caller always
    receives a FeatureSet, never an exception from this function.

    Args:
        market_state: Current validated market snapshot.
        events: Detected events from Event Detection Agent.

    Returns:
        FeatureSet with all successfully computed signals.
        feature_errors contains one entry per failed signal computation.
    """
    feature_errors: list[str] = []
    volatility_gaps: list[VolatilityGap] = []
    sector_dispersion: float | None = None
    supply_shock_probability: float | None = None

    try:
        volatility_gaps = compute_volatility_gap(market_state)
    except Exception as exc:
        msg = f"compute_volatility_gap failed: {exc}"
        logger.warning(msg)
        feature_errors.append(msg)

    try:
        sector_dispersion = compute_sector_dispersion(market_state)
    except Exception as exc:
        msg = f"compute_sector_dispersion failed: {exc}"
        logger.warning(msg)
        feature_errors.append(msg)

    try:
        supply_shock_probability = compute_supply_shock_probability(events)
    except Exception as exc:
        msg = f"compute_supply_shock_probability failed: {exc}"
        logger.warning(msg)
        feature_errors.append(msg)

    feature_set = FeatureSet(
        snapshot_time=market_state.snapshot_time,
        volatility_gaps=volatility_gaps,
        sector_dispersion=sector_dispersion,
        supply_shock_probability=supply_shock_probability,
        feature_errors=feature_errors,
    )

    # Persist to DB — failures logged but not propagated (degraded-mode).
    # A DB outage must not suppress the FeatureSet from the caller.
    try:
        engine = get_engine()
        write_feature_set(feature_set, engine)
    except Exception as exc:
        # ERROR (not WARNING) — a silent persistence failure is not recoverable
        # from the caller's perspective and must be observable in logs/alerts.
        logger.error("Failed to persist FeatureSet: %s", exc)

    return feature_set
