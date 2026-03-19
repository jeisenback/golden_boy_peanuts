"""
Unit tests for run_pipeline() — Phase 2 wiring.

Validates:
  - Event detection results are passed through to feature generation
  - Degraded mode: event detection failure → events=[], pipeline continues
  - Pipeline returns StrategyCandidate list from evaluate_strategies
  - Empty events list when event detection returns no events
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from unittest.mock import MagicMock, patch

import pytest

from src.agents.event_detection.event_detection_agent import EventDetectionError
from src.agents.event_detection.models import DetectedEvent, EventIntensity, EventType
from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.ingestion.models import MarketState
from src.agents.strategy_evaluation.models import StrategyCandidate
from src.pipeline import run_pipeline

# Patch targets — must match import paths in src/pipeline.py
_PATCH_INGESTION = "src.pipeline.run_ingestion"
_PATCH_EVENT_DETECTION = "src.pipeline.run_event_detection"
_PATCH_FEATURE_GENERATION = "src.pipeline.run_feature_generation"
_PATCH_EVALUATE = "src.pipeline.evaluate_strategies"


def _make_market_state() -> MarketState:
    return MarketState(
        snapshot_time=datetime.now(tz=UTC),
        prices=[],
        options=[],
    )


def _make_feature_set() -> FeatureSet:
    return FeatureSet(snapshot_time=datetime.now(tz=UTC))


def _make_market_only_feature_set() -> FeatureSet:
    return FeatureSet(
        snapshot_time=datetime.now(tz=UTC),
        volatility_gaps=[
            VolatilityGap(
                instrument="USO",
                realized_vol=0.15,
                implied_vol=0.25,
                gap=0.10,
                computed_at=datetime.now(tz=UTC),
            )
        ],
        sector_dispersion=0.10,
    )


def _make_event(description: str = "Test event") -> DetectedEvent:
    return DetectedEvent(
        event_id="test-001",
        event_type=EventType.SUPPLY_DISRUPTION,
        description=description,
        source="test",
        confidence_score=0.8,
        intensity=EventIntensity.HIGH,
        detected_at=datetime.now(tz=UTC),
        affected_instruments=["CL=F"],
    )


class TestRunPipeline:
    """Tests for run_pipeline() Phase 2 wiring."""

    def test_events_passed_to_feature_generation(self) -> None:
        """run_event_detection() output flows into run_feature_generation(events=...)."""
        events = [_make_event("Supply cut")]
        ms = _make_market_state()
        fs = _make_feature_set()

        with (
            patch(_PATCH_INGESTION, return_value=ms),
            patch(_PATCH_EVENT_DETECTION, return_value=events),
            patch(_PATCH_FEATURE_GENERATION, return_value=fs) as mock_fg,
            patch(_PATCH_EVALUATE, return_value=[]),
        ):
            run_pipeline()

        mock_fg.assert_called_once_with(ms, events=events)

    def test_degraded_mode_on_event_detection_failure(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Event detection exception logs degraded mode and still returns candidates."""
        ms = _make_market_state()
        fs = _make_market_only_feature_set()

        with (
            patch(_PATCH_INGESTION, return_value=ms),
            patch(_PATCH_EVENT_DETECTION, side_effect=EventDetectionError("API down")),
            patch(_PATCH_FEATURE_GENERATION, return_value=fs) as mock_fg,
        ):
            with caplog.at_level(logging.WARNING):
                result = run_pipeline()

        mock_fg.assert_called_once_with(ms, events=[])
        assert result
        assert all(isinstance(candidate, StrategyCandidate) for candidate in result)
        assert "degraded mode" in caplog.text
        assert all(candidate.signals["supply_shock_probability"] == "none" for candidate in result)
        assert all(candidate.signals["futures_curve_steepness"] == "flat" for candidate in result)

    def test_non_recoverable_exception_propagates(self) -> None:
        """Non-recoverable exceptions (e.g. AttributeError) propagate."""
        ms = _make_market_state()

        with (
            patch(_PATCH_INGESTION, return_value=ms),
            patch(_PATCH_EVENT_DETECTION, side_effect=AttributeError("Programming error")),
        ):
            # AttributeError is not in the caught exception set, so it should propagate
            with pytest.raises(AttributeError, match="Programming error"):
                run_pipeline()

    def test_returns_strategy_candidates(self) -> None:
        """run_pipeline() returns the list from evaluate_strategies()."""
        ms = _make_market_state()
        fs = _make_feature_set()
        candidates = [MagicMock(spec=StrategyCandidate)]

        with (
            patch(_PATCH_INGESTION, return_value=ms),
            patch(_PATCH_EVENT_DETECTION, return_value=[]),
            patch(_PATCH_FEATURE_GENERATION, return_value=fs),
            patch(_PATCH_EVALUATE, return_value=candidates),
        ):
            result = run_pipeline()

        assert result is candidates

    def test_empty_events_when_detection_returns_none(self) -> None:
        """When event detection returns an empty list, events=[] passed through."""
        ms = _make_market_state()
        fs = _make_feature_set()

        with (
            patch(_PATCH_INGESTION, return_value=ms),
            patch(_PATCH_EVENT_DETECTION, return_value=[]),
            patch(_PATCH_FEATURE_GENERATION, return_value=fs) as mock_fg,
            patch(_PATCH_EVALUATE, return_value=[]),
        ):
            run_pipeline()

        mock_fg.assert_called_once_with(ms, events=[])
