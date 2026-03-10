"""
Unit tests for the Strategy Evaluation Agent.

Coverage goal (expand per GitHub Issue):
  - evaluate_strategies: returns list of StrategyCandidate sorted by edge_score DESC
  - StrategyCandidate fields match PRD Section 9 schema exactly
  - compute_edge_score: returns float in [0.0, 1.0]
"""

from datetime import UTC, datetime

import pytest

from src.agents.feature_generation.models import FeatureSet
from src.agents.strategy_evaluation.models import StrategyCandidate
from src.agents.strategy_evaluation.strategy_evaluation_agent import evaluate_strategies


class TestEvaluateStrategies:
    """Tests for evaluate_strategies() function."""

    @pytest.mark.xfail(reason="Not yet implemented", strict=True)
    def test_evaluate_strategies_returns_list(self) -> None:
        """evaluate_strategies() must return a list of StrategyCandidate."""
        feature_set = FeatureSet(snapshot_time=datetime.now(tz=UTC))
        result = evaluate_strategies(feature_set)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, StrategyCandidate)

    @pytest.mark.xfail(reason="Not yet implemented", strict=True)
    def test_candidates_sorted_by_edge_score_desc(self) -> None:
        """evaluate_strategies() output must be sorted by edge_score descending."""
        feature_set = FeatureSet(snapshot_time=datetime.now(tz=UTC))
        result = evaluate_strategies(feature_set)
        scores = [c.edge_score for c in result]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.xfail(reason="Not yet implemented", strict=True)
    def test_strategy_candidate_matches_prd_schema(self) -> None:
        """
        StrategyCandidate must have all PRD Section 9 output schema fields:
        instrument, structure, expiration, edge_score, signals, generated_at
        """
        feature_set = FeatureSet(snapshot_time=datetime.now(tz=UTC))
        result = evaluate_strategies(feature_set)
        if result:
            candidate = result[0]
            assert hasattr(candidate, "instrument")
            assert hasattr(candidate, "structure")
            assert hasattr(candidate, "expiration")
            assert hasattr(candidate, "edge_score")
            assert hasattr(candidate, "signals")
            assert hasattr(candidate, "generated_at")
