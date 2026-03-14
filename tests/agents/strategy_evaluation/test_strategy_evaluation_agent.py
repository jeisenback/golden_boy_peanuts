"""
Unit tests for the Strategy Evaluation Agent.

Coverage goal (expand per GitHub Issue):
  - evaluate_strategies: returns list of StrategyCandidate sorted by edge_score DESC
  - StrategyCandidate fields match PRD Section 9 schema exactly
  - compute_edge_score: returns float in [0.0, 1.0]
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.strategy_evaluation.models import StrategyCandidate
from src.agents.strategy_evaluation.strategy_evaluation_agent import (
    compute_edge_score,
    evaluate_strategies,
)

# Patch target for DB calls inside evaluate_strategies
_PATCH_GET_ENGINE = "src.agents.strategy_evaluation.strategy_evaluation_agent.get_engine"
_PATCH_WRITE = "src.agents.strategy_evaluation.strategy_evaluation_agent.write_strategy_candidates"


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
    """Tests for evaluate_strategies() function.

    DB calls (get_engine, write_strategy_candidates) are mocked in all tests
    so the suite runs without a live database.
    """

    @staticmethod
    def _mock_db() -> tuple[MagicMock, MagicMock]:
        """Return patched (get_engine, write_strategy_candidates) mocks."""
        return (
            patch(_PATCH_GET_ENGINE, return_value=MagicMock()),
            patch(_PATCH_WRITE, return_value=3),
        )

    def test_evaluate_strategies_returns_list(self) -> None:
        """evaluate_strategies() must return a list of StrategyCandidate."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=0.5)
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, StrategyCandidate)

    def test_candidates_sorted_by_edge_score_desc(self) -> None:
        """evaluate_strategies() output must be sorted by edge_score descending."""
        fs = _make_feature_set(
            [_make_vg("USO", 0.20), _make_vg("XLE", 0.10)], sector_dispersion=0.5
        )
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        scores = [c.edge_score for c in result]
        assert scores == sorted(scores, reverse=True)

    def test_strategy_candidate_matches_prd_schema(self) -> None:
        """StrategyCandidate has all PRD Section 9 output schema fields."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=0.5)
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        assert result, "Expected at least one candidate"
        candidate = result[0]
        assert hasattr(candidate, "instrument")
        assert hasattr(candidate, "structure")
        assert hasattr(candidate, "expiration")
        assert hasattr(candidate, "edge_score")
        assert hasattr(candidate, "signals")
        assert hasattr(candidate, "generated_at")

    def test_three_structures_per_instrument(self) -> None:
        """Each qualifying instrument produces 3 candidates (one per Phase 1 structure)."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=0.5)
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        uso_candidates = [c for c in result if c.instrument == "USO"]
        assert len(uso_candidates) == 3
        structures = {c.structure for c in uso_candidates}
        assert "long_straddle" in structures
        assert "call_spread" in structures
        assert "put_spread" in structures

    def test_below_threshold_filtered_out(self) -> None:
        """Instruments with edge_score < 0.10 produce no candidates."""
        # gap=0.0 → edge_score=0.0, which is below _MIN_EDGE_SCORE=0.10
        fs = _make_feature_set([_make_vg("USO", 0.0)], sector_dispersion=0.0)
        result = evaluate_strategies(fs)  # no candidates → DB not called
        assert result == []

    def test_empty_feature_set_returns_empty(self) -> None:
        """No volatility gaps → no candidates (all instruments score 0.0)."""
        fs = _make_feature_set([], sector_dispersion=1.0)
        result = evaluate_strategies(fs)  # no candidates → DB not called
        assert result == []

    def test_expiration_is_30_days(self) -> None:
        """All Phase 1 candidates use _DEFAULT_EXPIRATION_DAYS = 30."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=0.5)
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        assert all(c.expiration == 30 for c in result)

    def test_signals_dict_keys(self) -> None:
        """signals dict must contain 'volatility_gap' and 'sector_dispersion' keys."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=0.5)
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        assert result
        assert "volatility_gap" in result[0].signals
        assert "sector_dispersion" in result[0].signals

    def test_signals_positive_gap_high_dispersion(self) -> None:
        """Positive gap + high dispersion → correct signal labels."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=0.20)
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        uso = next(c for c in result if c.instrument == "USO")
        assert uso.signals["volatility_gap"] == "positive"
        assert uso.signals["sector_dispersion"] == "high"

    def test_signals_negative_gap(self) -> None:
        """Negative gap → 'negative' label (dispersion carries score above threshold)."""
        # With gap=-0.05 and dispersion=0.5, edge_score = 0 + 0.5*0.30 = 0.15 → above threshold
        fs = _make_feature_set([_make_vg("USO", -0.05)], sector_dispersion=0.5)
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        uso = next((c for c in result if c.instrument == "USO"), None)
        assert uso is not None
        assert uso.signals["volatility_gap"] == "negative"
