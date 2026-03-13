"""
Unit tests for the Strategy Evaluation Agent.

Coverage goal (expand per GitHub Issue):
  - evaluate_strategies: returns list of StrategyCandidate sorted by edge_score DESC
  - StrategyCandidate fields match PRD Section 9 schema exactly
  - compute_edge_score: returns float in [0.0, 1.0]
"""

from datetime import UTC, datetime

import pytest

from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.strategy_evaluation.models import StrategyCandidate
from src.agents.strategy_evaluation.strategy_evaluation_agent import (
    compute_edge_score,
    evaluate_strategies,
)


def _make_vg(instrument: str, gap: float) -> VolatilityGap:
    return VolatilityGap(
        instrument=instrument,
        realized_vol=0.20,
        implied_vol=0.20 + gap,
        gap=gap,
        computed_at=datetime.now(tz=UTC),
    )


def _make_feature_set(
    gaps: list[VolatilityGap],
    sector_dispersion: float | None = None,
) -> FeatureSet:
    return FeatureSet(
        snapshot_time=datetime.now(tz=UTC),
        volatility_gaps=gaps,
        sector_dispersion=sector_dispersion,
    )


class TestComputeEdgeScore:
    """Tests for compute_edge_score()."""

    def test_high_gap_high_dispersion(self) -> None:
        """Full vol gap + full dispersion → 1.0."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=1.0)
        score = compute_edge_score("USO", fs)
        assert abs(score - 1.0) < 1e-9

    def test_full_gap_no_dispersion(self) -> None:
        """Full vol gap, dispersion None → 0.70."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=None)
        score = compute_edge_score("USO", fs)
        assert abs(score - 0.70) < 1e-9

    def test_low_gap(self) -> None:
        """Half vol gap, half dispersion → 0.35 + 0.15 = 0.50."""
        fs = _make_feature_set([_make_vg("XLE", 0.10)], sector_dispersion=0.50)
        score = compute_edge_score("XLE", fs)
        assert abs(score - 0.50) < 1e-9

    def test_gap_capped_at_one(self) -> None:
        """Vol gap larger than 0.20 caps at 1.0 contribution, so score ≤ 1.0."""
        fs = _make_feature_set([_make_vg("XOM", 0.50)], sector_dispersion=1.0)
        score = compute_edge_score("XOM", fs)
        assert abs(score - 1.0) < 1e-9

    def test_no_instrument_returns_zero(self) -> None:
        """Instrument not in feature_set.volatility_gaps → 0.0."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=1.0)
        score = compute_edge_score("XOM", fs)
        assert score == 0.0

    def test_negative_gap_returns_zero(self) -> None:
        """Negative vol gap (IV below realized) clipped to 0 → 0.0 vol contribution."""
        fs = _make_feature_set([_make_vg("CVX", -0.05)], sector_dispersion=None)
        score = compute_edge_score("CVX", fs)
        assert score == 0.0

    def test_zero_dispersion(self) -> None:
        """Full gap, zero dispersion → 0.70."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=0.0)
        score = compute_edge_score("USO", fs)
        assert abs(score - 0.70) < 1e-9

    def test_score_bounded(self) -> None:
        """Edge score must always be in [0.0, 1.0]."""
        fs = _make_feature_set([_make_vg("USO", 1.0)], sector_dispersion=1.0)
        score = compute_edge_score("USO", fs)
        assert 0.0 <= score <= 1.0


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
