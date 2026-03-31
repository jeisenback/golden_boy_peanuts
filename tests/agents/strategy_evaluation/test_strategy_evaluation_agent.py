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
    supply_shock_probability: float | None = None,
    futures_curve_steepness: float | None = None,
) -> FeatureSet:
    return FeatureSet(
        snapshot_time=datetime.now(tz=UTC),
        volatility_gaps=gaps,
        sector_dispersion=sector_dispersion,
        supply_shock_probability=supply_shock_probability,
        futures_curve_steepness=futures_curve_steepness,
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

    # --- Phase 2 multiplier tests ---

    def test_phase1_unchanged_when_none(self) -> None:
        """When supply_shock and curve_steepness are None, score matches Phase 1."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=0.5)
        score_none = compute_edge_score(
            "USO",
            fs,
            supply_shock_probability=None,
            futures_curve_steepness=None,
        )
        score_base = compute_edge_score("USO", fs)
        assert score_none == score_base

    def test_supply_shock_increases_score(self) -> None:
        """supply_shock_probability=0.8 increases score vs None."""
        fs = _make_feature_set([_make_vg("USO", 0.10)], sector_dispersion=0.2)
        base = compute_edge_score("USO", fs)
        boosted = compute_edge_score("USO", fs, supply_shock_probability=0.8)
        assert boosted > base

    def test_curve_steepness_increases_score(self) -> None:
        """Non-zero futures_curve_steepness increases edge score."""
        fs = _make_feature_set([_make_vg("USO", 0.10)], sector_dispersion=0.2)
        base = compute_edge_score("USO", fs)
        boosted = compute_edge_score("USO", fs, futures_curve_steepness=0.05)
        assert boosted > base

    def test_both_multipliers_compound(self) -> None:
        """Both multipliers together produce a higher score than either alone."""
        fs = _make_feature_set([_make_vg("USO", 0.10)], sector_dispersion=0.2)
        shock_only = compute_edge_score("USO", fs, supply_shock_probability=0.5)
        curve_only = compute_edge_score("USO", fs, futures_curve_steepness=0.05)
        both = compute_edge_score(
            "USO",
            fs,
            supply_shock_probability=0.5,
            futures_curve_steepness=0.05,
        )
        assert both > shock_only
        assert both > curve_only

    def test_multipliers_cap_at_one(self) -> None:
        """Even with large multipliers, score is capped at 1.0."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=1.0)
        score = compute_edge_score(
            "USO",
            fs,
            supply_shock_probability=1.0,
            futures_curve_steepness=0.5,
        )
        assert score == 1.0

    def test_negative_curve_steepness_uses_abs(self) -> None:
        """Negative curve steepness (backwardation) also boosts score via abs()."""
        fs = _make_feature_set([_make_vg("USO", 0.10)], sector_dispersion=0.2)
        pos = compute_edge_score("USO", fs, futures_curve_steepness=0.05)
        neg = compute_edge_score("USO", fs, futures_curve_steepness=-0.05)
        assert abs(pos - neg) < 1e-9

    def test_zero_effect_inputs_equivalent_to_none(self) -> None:
        """supply_shock=0.0 and curve_steepness=0.0 match None/None behavior."""
        fs = _make_feature_set([_make_vg("USO", 0.10)], sector_dispersion=0.2)
        score_none = compute_edge_score(
            "USO",
            fs,
            supply_shock_probability=None,
            futures_curve_steepness=None,
        )
        score_zero = compute_edge_score(
            "USO",
            fs,
            supply_shock_probability=0.0,
            futures_curve_steepness=0.0,
        )
        assert score_zero == score_none


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
        assert hasattr(candidate, "data_quality")
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
        """signals dict must contain all four signal keys."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=0.5)
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        assert result
        assert "volatility_gap" in result[0].signals
        assert "sector_dispersion" in result[0].signals
        assert "supply_shock_probability" in result[0].signals
        assert "futures_curve_steepness" in result[0].signals

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

    def test_supply_shock_label_high(self) -> None:
        """supply_shock_probability > 0.6 → 'high' label."""
        fs = _make_feature_set(
            [_make_vg("USO", 0.20)],
            sector_dispersion=0.5,
            supply_shock_probability=0.8,
        )
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        assert result[0].signals["supply_shock_probability"] == "high"

    def test_supply_shock_label_none(self) -> None:
        """supply_shock_probability None → 'none' label."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=0.5)
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        assert result[0].signals["supply_shock_probability"] == "none"

    def test_curve_steepness_label_contango(self) -> None:
        """Positive futures_curve_steepness → 'contango' label."""
        fs = _make_feature_set(
            [_make_vg("USO", 0.20)],
            sector_dispersion=0.5,
            futures_curve_steepness=0.03,
        )
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        assert result[0].signals["futures_curve_steepness"] == "contango"

    def test_curve_steepness_label_backwardation(self) -> None:
        """Negative futures_curve_steepness → 'backwardation' label."""
        fs = _make_feature_set(
            [_make_vg("USO", 0.20)],
            sector_dispersion=0.5,
            futures_curve_steepness=-0.02,
        )
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        assert result[0].signals["futures_curve_steepness"] == "backwardation"

    def test_curve_steepness_label_flat(self) -> None:
        """futures_curve_steepness None → 'flat' label."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=0.5)
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        assert result[0].signals["futures_curve_steepness"] == "flat"

    def test_evaluate_passes_phase2_signals_to_edge_score(self) -> None:
        """evaluate_strategies passes feature_set Phase 2 fields to compute_edge_score."""
        fs = _make_feature_set(
            [_make_vg("USO", 0.10)],
            sector_dispersion=0.2,
            supply_shock_probability=0.5,
            futures_curve_steepness=0.04,
        )
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        # With Phase 2 multipliers the score should be higher than Phase 1 base
        fs_none = _make_feature_set([_make_vg("USO", 0.10)], sector_dispersion=0.2)
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result_none = evaluate_strategies(fs_none)
        assert result[0].edge_score > result_none[0].edge_score

    def test_correlated_instruments_yield_18_equal_score_candidates(self) -> None:
        """All 6 in-scope instruments above threshold produce 18 deterministic candidates.

        18 candidates is expected behavior when all instruments are correlated;
        see concentration filter issue #132 for future de-duplication behavior.
        """
        instruments = ["USO", "XLE", "XOM", "CVX", "CL=F", "BZ=F"]
        fs = _make_feature_set(
            [_make_vg(instrument, 0.20) for instrument in instruments],
            sector_dispersion=0.50,
        )

        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)

        assert len(result) == 18
        assert len({candidate.edge_score for candidate in result}) == 1

        # All scores are equal, so sorted(desc) preserves insertion order (stable sort).
        assert [candidate.edge_score for candidate in result] == sorted(
            (candidate.edge_score for candidate in result),
            reverse=True,
        )

        expected_order = [
            ("USO", "long_straddle"),
            ("USO", "call_spread"),
            ("USO", "put_spread"),
            ("XLE", "long_straddle"),
            ("XLE", "call_spread"),
            ("XLE", "put_spread"),
            ("XOM", "long_straddle"),
            ("XOM", "call_spread"),
            ("XOM", "put_spread"),
            ("CVX", "long_straddle"),
            ("CVX", "call_spread"),
            ("CVX", "put_spread"),
            ("CL=F", "long_straddle"),
            ("CL=F", "call_spread"),
            ("CL=F", "put_spread"),
            ("BZ=F", "long_straddle"),
            ("BZ=F", "call_spread"),
            ("BZ=F", "put_spread"),
        ]
        actual_order = [(candidate.instrument, candidate.structure) for candidate in result]
        assert actual_order == expected_order


class TestDataQuality:
    """Tests for data_quality field on StrategyCandidate (issue #131)."""

    def test_all_signals_present_returns_all_available(self) -> None:
        """Candidate generated with all signals having real non-zero data → all keys 'available'."""
        fs = _make_feature_set(
            [_make_vg("USO", 0.20)],
            sector_dispersion=0.5,
            supply_shock_probability=0.7,
            futures_curve_steepness=0.05,
        )
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        assert result, "Expected at least one candidate"
        uso = next(c for c in result if c.instrument == "USO")
        assert uso.data_quality["volatility_gap"] == "available"
        assert uso.data_quality["sector_dispersion"] == "available"
        assert uso.data_quality["supply_shock_probability"] == "available"
        assert uso.data_quality["futures_curve_steepness"] == "available"

    def test_missing_volatility_gap_record_yields_no_candidate(self) -> None:
        """Instrument with no VolatilityGap record in feature_set generates no candidates.
        (compute_edge_score returns 0.0 → below _MIN_EDGE_SCORE threshold — data_quality
        'unavailable' for volatility_gap is therefore unreachable for a generated candidate.)"""
        fs = _make_feature_set([], sector_dispersion=0.5)
        result = evaluate_strategies(fs)  # no candidates → DB not called
        assert result == [], "Expected no candidates when volatility_gaps is empty"

    def test_none_phase2_signals_return_unavailable(self) -> None:
        """Candidate generated with supply_shock_probability=None and
        futures_curve_steepness=None → those keys are 'unavailable' in data_quality."""
        fs = _make_feature_set(
            [_make_vg("USO", 0.20)],
            sector_dispersion=0.5,
            supply_shock_probability=None,
            futures_curve_steepness=None,
        )
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        assert result, "Expected at least one candidate"
        uso = next(c for c in result if c.instrument == "USO")
        assert uso.data_quality["supply_shock_probability"] == "unavailable"
        assert uso.data_quality["futures_curve_steepness"] == "unavailable"
        assert uso.data_quality["volatility_gap"] == "available"
        assert uso.data_quality["sector_dispersion"] == "available"

    def test_zero_value_signals_return_defaulted_zero(self) -> None:
        """Candidate generated with sector_dispersion=0.0 and futures_curve_steepness=0.0
        → those keys are 'defaulted_zero' in data_quality."""
        fs = _make_feature_set(
            [_make_vg("USO", 0.20)],
            sector_dispersion=0.0,
            supply_shock_probability=0.0,
            futures_curve_steepness=0.0,
        )
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        assert result, "Expected at least one candidate"
        uso = next(c for c in result if c.instrument == "USO")
        assert uso.data_quality["sector_dispersion"] == "defaulted_zero"
        assert uso.data_quality["supply_shock_probability"] == "defaulted_zero"
        assert uso.data_quality["futures_curve_steepness"] == "defaulted_zero"
        assert uso.data_quality["volatility_gap"] == "available"

    def test_zero_gap_returns_defaulted_zero(self) -> None:
        """VolatilityGap record with gap=0.0 → volatility_gap: 'defaulted_zero'.
        (Candidate generated when sector_dispersion provides enough base score.)"""
        fs = _make_feature_set(
            [_make_vg("USO", 0.0)],
            sector_dispersion=1.0,  # provides 0.30 base score > 0.10 threshold
        )
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        assert result, "Expected at least one candidate (dispersion alone clears threshold)"
        uso = next(c for c in result if c.instrument == "USO")
        assert uso.data_quality["volatility_gap"] == "defaulted_zero"
