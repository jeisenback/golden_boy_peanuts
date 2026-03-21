"""
Shared pytest fixtures for the Energy Options Opportunity Agent test suite.

Provides minimal but realistic instances of the four core Pydantic boundary
models used across all agent tests:

    sample_market_state     → MarketState (ingestion output)
    sample_detected_event   → DetectedEvent (event detection output)
    sample_feature_set      → FeatureSet (feature generation output)
    sample_strategy_candidate → StrategyCandidate (strategy evaluation output)

Supporting sub-object fixtures are also exposed for tests that need
to compose their own parent models.

All datetime values use timezone-aware UTC timestamps.
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.agents.event_detection.models import (
    DetectedEvent,
    EventIntensity,
    EventType,
)
from src.agents.feature_generation.models import (
    FeatureSet,
    VolatilityGap,
)
from src.agents.ingestion.models import (
    InstrumentType,
    MarketState,
    OptionRecord,
    OptionStructure,
    RawPriceRecord,
)
from src.agents.strategy_evaluation.models import StrategyCandidate

# ---------------------------------------------------------------------------
# Shared timestamp
# ---------------------------------------------------------------------------

_TS = datetime.now(tz=UTC).replace(microsecond=0)
_TS_EXP = _TS + timedelta(days=90)


# ---------------------------------------------------------------------------
# Sub-object fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_raw_price_record() -> RawPriceRecord:
    """A single USO ETF price record."""
    return RawPriceRecord(
        instrument="USO",
        instrument_type=InstrumentType.ETF,
        price=80.0,
        volume=120_000,
        timestamp=_TS,
        source="test",
    )


@pytest.fixture()
def sample_option_record() -> OptionRecord:
    """A single USO call option record."""
    return OptionRecord(
        instrument="USO",
        strike=75.0,
        expiration_date=_TS_EXP,
        implied_volatility=0.32,
        open_interest=4500,
        volume=320,
        option_type="call",
        timestamp=_TS,
        source="test",
    )


@pytest.fixture()
def sample_volatility_gap() -> VolatilityGap:
    """A positive volatility gap on USO (implied > realized)."""
    return VolatilityGap(
        instrument="USO",
        realized_vol=0.25,
        implied_vol=0.38,
        gap=0.13,
        computed_at=_TS,
    )


# ---------------------------------------------------------------------------
# Primary boundary-model fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_market_state(
    sample_raw_price_record: RawPriceRecord,
    sample_option_record: OptionRecord,
) -> MarketState:
    """
    A populated MarketState representing a clean ingestion run.

    Contains two price records (USO ETF + WTI crude) and one option record
    (USO call), with no ingestion errors.
    """
    wti_price_record = RawPriceRecord(
        instrument="WTI",
        instrument_type=InstrumentType.CRUDE_FUTURES,
        price=78.45,
        volume=95_000,
        timestamp=_TS,
        source="test",
    )
    return MarketState(
        snapshot_time=_TS,
        prices=[sample_raw_price_record, wti_price_record],
        options=[sample_option_record],
        ingestion_errors=[],
    )


@pytest.fixture()
def sample_detected_event() -> DetectedEvent:
    """
    A SUPPLY_DISRUPTION event with HIGH intensity and 0.8 confidence.

    Affects WTI and USO. Includes a raw_headline for tests that validate
    the optional field path.
    """
    return DetectedEvent(
        event_id="evt-test-001",
        event_type=EventType.SUPPLY_DISRUPTION,
        description="Libyan pipeline outage reduces export capacity by 300k bpd.",
        source="test",
        confidence_score=0.8,
        intensity=EventIntensity.HIGH,
        detected_at=_TS,
        affected_instruments=["WTI", "USO"],
        raw_headline="Libya pipeline shut after armed attack — Reuters",
    )


@pytest.fixture()
def sample_feature_set(sample_volatility_gap: VolatilityGap) -> FeatureSet:
    """
    A FeatureSet with a positive vol gap and moderate supply shock probability.

    Optional numeric fields are populated with plausible values so feature
    presence tests don't need to add their own data.
    """
    return FeatureSet(
        snapshot_time=_TS,
        volatility_gaps=[sample_volatility_gap],
        futures_curve_steepness=1.2,
        sector_dispersion=0.15,
        insider_conviction_score=0.6,
        narrative_velocity=3.5,
        supply_shock_probability=0.72,
        feature_errors=[],
    )


@pytest.fixture()
def sample_strategy_candidate() -> StrategyCandidate:
    """
    A long straddle on USO expiring in 90 days.

    Uses the canonical edge_score=0.6 from Issue #29 AC — a minimum valid
    object that does not encode any assumed threshold.
    """
    return StrategyCandidate(
        instrument="USO",
        structure=OptionStructure.LONG_STRADDLE,
        expiration=90,
        edge_score=0.6,
        signals={
            "volatility_gap": "positive",
            "supply_shock_probability": "high",
            "narrative_velocity": "elevated",
        },
        generated_at=_TS,
    )
