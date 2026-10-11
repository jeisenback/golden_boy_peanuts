"""
Unit tests for run_pipeline() — Phase 2 wiring.

Validates:
  - Event detection results are passed through to feature generation
  - Degraded mode: event detection failure → events=[], pipeline continues
  - Pipeline returns StrategyCandidate list from evaluate_strategies
  - Empty events list when event detection returns no events
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
import logging
from unittest.mock import MagicMock, patch

import pytest

from src.agents.alternative_data.models import AlternativeDataState
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
_PATCH_ALT_DATA = "src.pipeline.run_alternative_data_ingestion"


def _make_alt_state() -> AlternativeDataState:
    return AlternativeDataState(snapshot_time=datetime.now(tz=UTC))


_ALT_STATE = _make_alt_state()


@pytest.fixture(autouse=True)
def _no_alt_data_network() -> Iterator[MagicMock]:
    """Keep every pipeline test off the network: alternative-data ingestion is stubbed."""
    with patch(_PATCH_ALT_DATA, return_value=_ALT_STATE) as mock_alt:
        yield mock_alt


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
        # Market-derived signal available when event detection is down. The curve has weight 0
        # (#240), so it reaches the output only as a label.
        futures_curve_steepness=-0.03,
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

        mock_fg.assert_called_once_with(ms, events=events, alternative_data_state=_ALT_STATE)

    def test_degraded_mode_on_event_detection_failure(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Event detection failure logs degraded mode; the run completes with no direction view.

        Without events there is no supply shock, and tanker and insider signals are not wired
        (#236), so no direction signal survives and no candidates are emitted.
        """
        ms = _make_market_state()
        fs = _make_market_only_feature_set()

        with (
            patch(_PATCH_INGESTION, return_value=ms),
            patch(_PATCH_EVENT_DETECTION, side_effect=EventDetectionError("API down")),
            patch(_PATCH_FEATURE_GENERATION, return_value=fs) as mock_fg,
        ):
            with caplog.at_level(logging.WARNING):
                result = run_pipeline()

        mock_fg.assert_called_once_with(ms, events=[], alternative_data_state=_ALT_STATE)
        assert result == []
        assert "degraded mode" in caplog.text

    def test_alternative_data_state_passed_to_feature_generation(
        self, _no_alt_data_network: MagicMock
    ) -> None:
        """run_alternative_data_ingestion() output flows into feature generation (#236)."""
        ms = _make_market_state()
        with (
            patch(_PATCH_INGESTION, return_value=ms),
            patch(_PATCH_EVENT_DETECTION, return_value=[]),
            patch(_PATCH_FEATURE_GENERATION, return_value=_make_feature_set()) as mock_fg,
            patch(_PATCH_EVALUATE, return_value=[]),
        ):
            run_pipeline()

        _no_alt_data_network.assert_called_once_with()
        assert mock_fg.call_args.kwargs["alternative_data_state"] is _ALT_STATE

    def test_degraded_mode_on_alternative_data_failure(
        self,
        _no_alt_data_network: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Alternative-data failure logs a warning and the pipeline continues with None (#236)."""
        _no_alt_data_network.side_effect = RuntimeError("feeds down")
        ms = _make_market_state()
        with (
            patch(_PATCH_INGESTION, return_value=ms),
            patch(_PATCH_EVENT_DETECTION, return_value=[]),
            patch(_PATCH_FEATURE_GENERATION, return_value=_make_feature_set()) as mock_fg,
            patch(_PATCH_EVALUATE, return_value=[]),
            caplog.at_level(logging.WARNING),
        ):
            run_pipeline()

        mock_fg.assert_called_once_with(ms, events=[], alternative_data_state=None)
        assert "Alternative data ingestion failed (degraded mode)" in caplog.text
        assert "feeds down" in caplog.text

    def test_alternative_data_signals_reach_strategy_evaluation(self) -> None:
        """The FeatureSet that feature generation returns, with the three signals, is what
        evaluate_strategies() receives (#236)."""
        fs = FeatureSet(
            snapshot_time=datetime.now(tz=UTC),
            tanker_disruption_index=0.6,
            insider_conviction_score=0.9,
            narrative_velocity=0.4,
        )
        with (
            patch(_PATCH_INGESTION, return_value=_make_market_state()),
            patch(_PATCH_EVENT_DETECTION, return_value=[]),
            patch(_PATCH_FEATURE_GENERATION, return_value=fs),
            patch(_PATCH_EVALUATE, return_value=[]) as mock_eval,
        ):
            run_pipeline()

        passed = mock_eval.call_args.args[0]
        assert passed.tanker_disruption_index == pytest.approx(0.6)
        assert passed.insider_conviction_score == pytest.approx(0.9)
        assert passed.narrative_velocity == pytest.approx(0.4)

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

        mock_fg.assert_called_once_with(ms, events=[], alternative_data_state=_ALT_STATE)
