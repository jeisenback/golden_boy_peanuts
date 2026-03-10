"""
Unit tests for the Feature Generation Agent.

Coverage goal (expand per GitHub Issue):
  - run_feature_generation: returns FeatureSet
  - compute_supply_shock_probability: returns float in [0.0, 1.0]
  - compute_volatility_gap: returns VolatilityGap with correct gap calculation
  - Partial signal failure populates feature_errors, does not raise
"""
from datetime import UTC, datetime

import pytest

from src.agents.event_detection.models import DetectedEvent
from src.agents.feature_generation.feature_generation_agent import run_feature_generation
from src.agents.feature_generation.models import FeatureSet
from src.agents.ingestion.models import MarketState


class TestRunFeatureGeneration:
    """Tests for run_feature_generation() orchestration function."""

    @pytest.mark.xfail(reason="Not yet implemented", strict=True)
    def test_run_feature_generation_returns_feature_set(self) -> None:
        """run_feature_generation() must return a FeatureSet instance."""
        market_state = MarketState(snapshot_time=datetime.now(tz=UTC))
        events: list[DetectedEvent] = []
        result = run_feature_generation(market_state, events)
        assert isinstance(result, FeatureSet)

    @pytest.mark.xfail(reason="Not yet implemented", strict=True)
    def test_partial_signal_failure_does_not_raise(self) -> None:
        """
        If one signal computation fails, run_feature_generation() must return a
        partial FeatureSet with the error in feature_errors, not raise an exception.
        """
        market_state = MarketState(snapshot_time=datetime.now(tz=UTC))
        events: list[DetectedEvent] = []
        result = run_feature_generation(market_state, events)
        assert isinstance(result.feature_errors, list)
