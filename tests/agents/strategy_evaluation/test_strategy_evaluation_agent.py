"""
Unit tests for the Strategy Evaluation Agent.

Coverage goal (expand per GitHub Issue):
  - evaluate_strategies: returns list of StrategyCandidate sorted by edge_score DESC
  - StrategyCandidate fields match PRD Section 9 schema exactly
  - compute_edge_score: returns float in [0.0, 1.0]
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.ingestion.models import OptionStructure
from src.agents.strategy_evaluation.models import StrategyCandidate
from src.agents.strategy_evaluation.strategy_evaluation_agent import (
    INSTRUMENTS_IN_SCOPE,
    SIGNAL_ONLY_INSTRUMENTS,
    TRADEABLE_INSTRUMENTS,
    compute_direction_net,
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
    insider_conviction_score: float | None = None,
    narrative_velocity: float | None = None,
    tanker_disruption_index: float | None = None,
) -> FeatureSet:
    return FeatureSet(
        snapshot_time=datetime.now(tz=UTC),
        volatility_gaps=gaps,
        sector_dispersion=sector_dispersion,
        supply_shock_probability=supply_shock_probability,
        futures_curve_steepness=futures_curve_steepness,
        insider_conviction_score=insider_conviction_score,
        narrative_velocity=narrative_velocity,
        tanker_disruption_index=tanker_disruption_index,
    )


class TestComputeEdgeScore:
    """Structure-specific edge score from the signed direction net (#134)."""

    @staticmethod
    def _score(
        structure: OptionStructure,
        instrument: str = "USO",
        gaps: list[VolatilityGap] | None = None,
        sector_dispersion: float | None = None,
        **signals: float | None,
    ) -> float:
        fs = _make_feature_set(gaps or [], sector_dispersion=sector_dispersion)
        return compute_edge_score(instrument, fs, structure, **signals)

    def test_bullish_signal_scores_call_spread_only(self) -> None:
        call = self._score(OptionStructure.CALL_SPREAD, supply_shock_probability=1.0)
        put = self._score(OptionStructure.PUT_SPREAD, supply_shock_probability=1.0)
        assert call == pytest.approx(0.35)
        assert put == 0.0

    def test_bearish_signal_scores_put_spread_only(self) -> None:
        call = self._score(OptionStructure.CALL_SPREAD, futures_curve_steepness=0.05)
        put = self._score(OptionStructure.PUT_SPREAD, futures_curve_steepness=0.05)
        assert call == 0.0
        assert put == pytest.approx(0.25)

    def test_dispersion_amplifies_the_net(self) -> None:
        score = self._score(
            OptionStructure.CALL_SPREAD, sector_dispersion=0.5, supply_shock_probability=1.0
        )
        assert score == pytest.approx(0.4025)  # 0.35 * (1 + 0.30 * 0.5)

    def test_narrative_amplifier_is_capped_at_one(self) -> None:
        score = self._score(
            OptionStructure.CALL_SPREAD, supply_shock_probability=1.0, narrative_velocity=2.0
        )
        assert score == pytest.approx(0.385)  # 0.35 * (1 + 0.10 * 1.0)

    def test_score_is_clamped_at_one(self) -> None:
        score = self._score(
            OptionStructure.CALL_SPREAD,
            sector_dispersion=0.5,
            supply_shock_probability=1.0,
            futures_curve_steepness=-0.05,
            tanker_disruption_index=1.0,
            narrative_velocity=0.5,
        )
        assert score == 1.0  # 0.85 * 1.20 = 1.02, clamped

    def test_volatility_gap_has_no_effect(self) -> None:
        with_gap = self._score(
            OptionStructure.CALL_SPREAD,
            gaps=[_make_vg("USO", 0.20)],
            supply_shock_probability=1.0,
        )
        without_gap = self._score(OptionStructure.CALL_SPREAD, supply_shock_probability=1.0)
        assert with_gap == without_gap == pytest.approx(0.35)

    def test_no_signals_scores_zero_without_a_volatility_gap_record(self) -> None:
        assert self._score(OptionStructure.CALL_SPREAD) == 0.0
        assert self._score(OptionStructure.PUT_SPREAD) == 0.0

    @pytest.mark.parametrize(
        "structure", [OptionStructure.LONG_STRADDLE, OptionStructure.CALENDAR_SPREAD]
    )
    def test_unsupported_structure_raises(self, structure: OptionStructure) -> None:
        with pytest.raises(ValueError):
            self._score(structure, supply_shock_probability=1.0)


class TestComputeDirectionNet:
    """Signed direction net in [-1, 1]; positive means bullish crude (#134 spec 3.2, 3.3)."""

    @staticmethod
    def _net(instrument: str = "USO", **signals: float | None) -> float:
        params: dict[str, float | None] = {
            "supply_shock_probability": None,
            "futures_curve_steepness": None,
            "insider_conviction_score": None,
            "tanker_disruption_index": None,
        }
        params.update(signals)
        return compute_direction_net(instrument, **params)

    def test_supply_shock_alone_is_bullish_at_its_weight(self) -> None:
        assert self._net(supply_shock_probability=1.0) == pytest.approx(0.35)

    def test_tanker_disruption_alone_is_bullish_at_its_weight(self) -> None:
        assert self._net(tanker_disruption_index=1.0) == pytest.approx(0.25)

    def test_backwardation_is_bullish(self) -> None:
        assert self._net(futures_curve_steepness=-0.05) == pytest.approx(0.25)

    def test_contango_is_bearish(self) -> None:
        assert self._net(futures_curve_steepness=0.05) == pytest.approx(-0.25)

    def test_extreme_curve_steepness_clips_to_full_strength(self) -> None:
        assert self._net(futures_curve_steepness=-0.5) == pytest.approx(0.25)

    def test_insider_buying_counts_for_xom(self) -> None:
        assert self._net("XOM", insider_conviction_score=0.9) == pytest.approx(0.12)

    def test_insider_selling_counts_for_cvx(self) -> None:
        assert self._net("CVX", insider_conviction_score=0.0) == pytest.approx(-0.15)

    @pytest.mark.parametrize("instrument", ["USO", "XLE"])
    def test_insider_signal_ignored_for_etfs(self, instrument: str) -> None:
        assert self._net(instrument, insider_conviction_score=0.9) == 0.0

    def test_opposing_signals_cancel(self) -> None:
        net = self._net(supply_shock_probability=0.5, futures_curve_steepness=0.035)
        assert net == pytest.approx(0.0, abs=1e-9)

    def test_all_signals_maxed_bullish_for_xom_is_one(self) -> None:
        net = self._net(
            "XOM",
            supply_shock_probability=1.0,
            futures_curve_steepness=-0.05,
            insider_conviction_score=1.0,
            tanker_disruption_index=1.0,
        )
        assert net == pytest.approx(1.0)

    def test_no_signals_is_zero(self) -> None:
        assert self._net() == 0.0


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

    def test_correlated_instruments_yield_12_equal_score_candidates(self) -> None:
        """All 4 tradeable instruments above threshold produce 12 deterministic candidates.

        Was 18 when CL=F and BZ=F also received candidates. Those two are signal-only
        since #219: they have no historical options data, so their outcomes can never be
        scored. They still feed every signal, but evaluate_strategies() emits nothing for
        them, even when their own score is above threshold (included below to prove it).
        12 candidates is expected when all tradeable instruments are correlated; see
        concentration filter issue #132 for future de-duplication behavior.
        """
        instruments = ["USO", "XLE", "XOM", "CVX", "CL=F", "BZ=F"]
        fs = _make_feature_set(
            [_make_vg(instrument, 0.20) for instrument in instruments],
            sector_dispersion=0.50,
        )

        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)

        assert len(result) == 12
        assert {candidate.instrument for candidate in result} == set(TRADEABLE_INSTRUMENTS)
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
        ]
        actual_order = [(candidate.instrument, candidate.structure) for candidate in result]
        assert actual_order == expected_order

    def test_instrument_universe_is_tradeable_plus_signal_only(self) -> None:
        """Scope constants stay disjoint and together equal the full universe (#219)."""
        assert not set(TRADEABLE_INSTRUMENTS) & set(SIGNAL_ONLY_INSTRUMENTS)
        assert INSTRUMENTS_IN_SCOPE == TRADEABLE_INSTRUMENTS + SIGNAL_ONLY_INSTRUMENTS
        assert SIGNAL_ONLY_INSTRUMENTS == ["CL=F", "BZ=F"]
        assert TRADEABLE_INSTRUMENTS == ["USO", "XLE", "XOM", "CVX"]

    def test_phase3_signals_on_feature_set_increase_edge_score(self) -> None:
        """Phase 3 signals present on the FeatureSet raise edge_score vs. them being None (#209)."""
        baseline_fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=0.5)
        phase3_fs = _make_feature_set(
            [_make_vg("USO", 0.20)],
            sector_dispersion=0.5,
            insider_conviction_score=0.8,
            narrative_velocity=0.6,
            tanker_disruption_index=0.7,
        )

        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            baseline_result = evaluate_strategies(baseline_fs)
            phase3_result = evaluate_strategies(phase3_fs)

        baseline_uso = next(c for c in baseline_result if c.instrument == "USO")
        phase3_uso = next(c for c in phase3_result if c.instrument == "USO")
        assert phase3_uso.edge_score > baseline_uso.edge_score

    def test_phase3_signals_none_matches_pre_209_behavior(self) -> None:
        """Omitting Phase 3 fields on the FeatureSet leaves edge_score unchanged."""
        fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=0.5)
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            result = evaluate_strategies(fs)
        uso = next(c for c in result if c.instrument == "USO")
        # Phase 3 kwargs omitted intentionally — mirrors the pre-#209 call site,
        # since fs itself has no Phase 3 fields set (all default to None).
        expected = compute_edge_score(
            "USO",
            fs,
            supply_shock_probability=fs.supply_shock_probability,
            futures_curve_steepness=fs.futures_curve_steepness,
        )
        assert uso.edge_score == pytest.approx(expected)
