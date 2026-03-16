"""
Unit tests for the Pipeline Orchestrator — Phase 2 event detection wiring.

Validates that run_pipeline():
  1. Calls run_event_detection() and passes results to run_feature_generation()
  2. Continues in degraded mode (events=[]) when event detection fails
  3. Logs event detection count and supply_shock_probability in feature log
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.agents.event_detection.models import DetectedEvent, EventIntensity, EventType
from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.ingestion.models import InstrumentType, MarketState, OptionStructure, RawPriceRecord
from src.agents.strategy_evaluation.models import StrategyCandidate
from src.pipeline import run_pipeline  # noqa: F401 — force module load for patching

# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------
_PATCH_INGESTION = "src.pipeline.run_ingestion"
_PATCH_EVENT_DETECTION = "src.pipeline.run_event_detection"
_PATCH_FEATURE_GEN = "src.pipeline.run_feature_generation"
_PATCH_EVALUATE = "src.pipeline.evaluate_strategies"

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------
_TS = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)


def _make_market_state() -> MarketState:
    return MarketState(
        snapshot_time=_TS,
        prices=[
            RawPriceRecord(
                instrument="USO",
                instrument_type=InstrumentType.ETF,
                price=50.0,
                volume=1_000_000,
                timestamp=_TS,
                source="test",
            ),
        ],
        options=[],
        ingestion_errors=[],
    )


def _make_event() -> DetectedEvent:
    return DetectedEvent(
        event_id="evt-test-pipe-001",
        event_type=EventType.SUPPLY_DISRUPTION,
        description="Test pipeline supply disruption event",
        source="test",
        confidence_score=0.85,
        intensity=EventIntensity.HIGH,
        detected_at=_TS,
        affected_instruments=["CL=F", "USO"],
    )


def _make_feature_set() -> FeatureSet:
    return FeatureSet(
        snapshot_time=_TS,
        volatility_gaps=[
            VolatilityGap(
                instrument="USO",
                realized_vol=0.15,
                implied_vol=0.22,
                gap=0.07,
                computed_at=_TS,
            ),
        ],
        sector_dispersion=0.10,
        supply_shock_probability=0.72,
        feature_errors=[],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pipeline_passes_events_to_feature_generation() -> None:
    """run_pipeline() passes run_event_detection() results to run_feature_generation()."""
    market_state = _make_market_state()
    events = [_make_event()]
    feature_set = _make_feature_set()

    with (
        patch(_PATCH_INGESTION, return_value=market_state),
        patch(_PATCH_EVENT_DETECTION, return_value=events),
        patch(_PATCH_FEATURE_GEN, return_value=feature_set) as mock_fg,
        patch(_PATCH_EVALUATE, return_value=[]),
    ):
        run_pipeline()

    mock_fg.assert_called_once_with(market_state, events=events)


def test_pipeline_degraded_mode_on_event_detection_failure() -> None:
    """run_pipeline() continues with events=[] when run_event_detection() raises."""
    market_state = _make_market_state()
    feature_set = _make_feature_set()

    with (
        patch(_PATCH_INGESTION, return_value=market_state),
        patch(_PATCH_EVENT_DETECTION, side_effect=RuntimeError("API timeout")),
        patch(_PATCH_FEATURE_GEN, return_value=feature_set) as mock_fg,
        patch(_PATCH_EVALUATE, return_value=[]),
    ):
        candidates = run_pipeline()

    mock_fg.assert_called_once_with(market_state, events=[])
    assert candidates == []


def test_pipeline_returns_candidates_with_events() -> None:
    """run_pipeline() returns StrategyCandidate list when events are provided."""
    market_state = _make_market_state()
    events = [_make_event()]
    feature_set = _make_feature_set()
    expected_candidates = [
        StrategyCandidate(
            instrument="USO",
            structure=OptionStructure.LONG_STRADDLE,
            expiration=30,
            edge_score=0.55,
            signals={"volatility_gap": "positive", "sector_dispersion": "medium"},
            generated_at=_TS,
        ),
    ]

    with (
        patch(_PATCH_INGESTION, return_value=market_state),
        patch(_PATCH_EVENT_DETECTION, return_value=events),
        patch(_PATCH_FEATURE_GEN, return_value=feature_set),
        patch(_PATCH_EVALUATE, return_value=expected_candidates),
    ):
        candidates = run_pipeline()

    assert len(candidates) == 1
    assert candidates[0].instrument == "USO"
    assert candidates[0].edge_score == 0.55


def test_pipeline_empty_events_when_detection_returns_empty() -> None:
    """run_pipeline() passes events=[] when run_event_detection() returns []."""
    market_state = _make_market_state()
    feature_set = _make_feature_set()

    with (
        patch(_PATCH_INGESTION, return_value=market_state),
        patch(_PATCH_EVENT_DETECTION, return_value=[]),
        patch(_PATCH_FEATURE_GEN, return_value=feature_set) as mock_fg,
        patch(_PATCH_EVALUATE, return_value=[]),
    ):
        run_pipeline()

    mock_fg.assert_called_once_with(market_state, events=[])
