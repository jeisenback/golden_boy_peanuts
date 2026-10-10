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
    """Tests for evaluate_strategies(): one directional spread per tradeable instrument.

    DB calls (get_engine, write_strategy_candidates) are mocked in all tests
    so the suite runs without a live database.
    """

    @staticmethod
    def _evaluate(fs: FeatureSet) -> list[StrategyCandidate]:
        with patch(_PATCH_GET_ENGINE, return_value=MagicMock()), patch(_PATCH_WRITE):
            return evaluate_strategies(fs)

    @staticmethod
    def _all_gaps() -> list[VolatilityGap]:
        return [_make_vg(instrument, 0.20) for instrument in INSTRUMENTS_IN_SCOPE]

    def test_evaluate_strategies_returns_list(self) -> None:
        result = self._evaluate(_make_feature_set([], supply_shock_probability=1.0))
        assert result
        assert all(isinstance(item, StrategyCandidate) for item in result)

    def test_candidates_sorted_by_edge_score_desc(self) -> None:
        # XOM and CVX also get insider buying (net 0.47); USO and XLE do not (net 0.35).
        fs = _make_feature_set([], supply_shock_probability=1.0, insider_conviction_score=0.9)
        result = self._evaluate(fs)
        assert [c.instrument for c in result] == ["XOM", "CVX", "USO", "XLE"]
        scores = [c.edge_score for c in result]
        assert scores == sorted(scores, reverse=True)

    def test_strategy_candidate_matches_prd_schema(self) -> None:
        candidate = self._evaluate(_make_feature_set([], supply_shock_probability=1.0))[0]
        for field in ("instrument", "structure", "expiration", "edge_score", "signals"):
            assert hasattr(candidate, field)
        assert candidate.generated_at.tzinfo is not None

    def test_bullish_signals_yield_four_call_spreads_in_universe_order(self) -> None:
        fs = _make_feature_set(
            self._all_gaps(),
            sector_dispersion=0.5,
            supply_shock_probability=1.0,
            futures_curve_steepness=-0.05,
            tanker_disruption_index=1.0,
        )
        result = self._evaluate(fs)
        assert [(c.instrument, c.structure) for c in result] == [
            ("USO", "call_spread"),
            ("XLE", "call_spread"),
            ("XOM", "call_spread"),
            ("CVX", "call_spread"),
        ]
        # net 0.85 (supply 0.35 + tanker 0.25 + curve 0.25) amplified by 1 + 0.30 * 0.5
        assert all(c.edge_score == pytest.approx(0.9775) for c in result)

    def test_signal_only_instruments_never_get_candidates(self) -> None:
        fs = _make_feature_set(self._all_gaps(), supply_shock_probability=1.0)
        instruments = {c.instrument for c in self._evaluate(fs)}
        assert instruments == set(TRADEABLE_INSTRUMENTS)

    def test_bearish_signals_yield_four_put_spreads(self) -> None:
        result = self._evaluate(_make_feature_set([], futures_curve_steepness=0.05))
        assert [(c.instrument, c.structure) for c in result] == [
            ("USO", "put_spread"),
            ("XLE", "put_spread"),
            ("XOM", "put_spread"),
            ("CVX", "put_spread"),
        ]
        assert all(c.edge_score == pytest.approx(0.25) for c in result)

    def test_at_most_one_spread_per_instrument_and_never_a_straddle(self) -> None:
        fs = _make_feature_set([], supply_shock_probability=0.6, futures_curve_steepness=0.02)
        result = self._evaluate(fs)
        instruments = [c.instrument for c in result]
        assert len(instruments) == len(set(instruments))
        assert all(c.structure != "long_straddle" for c in result)

    def test_insider_selling_removes_equities_but_not_etfs(self) -> None:
        # XOM and CVX net 0.35 * 0.5 - 0.15 = 0.025, below the 0.10 threshold.
        fs = _make_feature_set([], supply_shock_probability=0.5, insider_conviction_score=0.0)
        assert [c.instrument for c in self._evaluate(fs)] == ["USO", "XLE"]

    def test_cancelling_signals_yield_no_candidates(self) -> None:
        fs = _make_feature_set([], supply_shock_probability=0.5, futures_curve_steepness=0.035)
        assert evaluate_strategies(fs) == []

    def test_below_threshold_filtered_out(self) -> None:
        # supply 0.2 gives net 0.07, below _MIN_EDGE_SCORE = 0.10
        assert evaluate_strategies(_make_feature_set([], supply_shock_probability=0.2)) == []

    def test_empty_feature_set_returns_empty(self) -> None:
        assert evaluate_strategies(_make_feature_set([], sector_dispersion=1.0)) == []

    def test_expiration_is_30_days(self) -> None:
        result = self._evaluate(_make_feature_set([], supply_shock_probability=1.0))
        assert result
        assert all(c.expiration == 30 for c in result)

    def test_signals_dict_keys_include_direction(self) -> None:
        candidate = self._evaluate(_make_feature_set([], supply_shock_probability=1.0))[0]
        for key in (
            "volatility_gap",
            "sector_dispersion",
            "supply_shock_probability",
            "futures_curve_steepness",
            "direction",
        ):
            assert key in candidate.signals

    def test_direction_label_matches_structure(self) -> None:
        bull = self._evaluate(_make_feature_set([], supply_shock_probability=1.0))[0]
        bear = self._evaluate(_make_feature_set([], futures_curve_steepness=0.05))[0]
        assert (bull.structure, bull.signals["direction"]) == ("call_spread", "bullish")
        assert (bear.structure, bear.signals["direction"]) == ("put_spread", "bearish")

    def test_volatility_gap_label_is_context_only(self) -> None:
        positive = _make_feature_set([_make_vg("USO", 0.20)], supply_shock_probability=1.0)
        negative = _make_feature_set([_make_vg("USO", -0.05)], supply_shock_probability=1.0)
        uso_pos = next(c for c in self._evaluate(positive) if c.instrument == "USO")
        uso_neg = next(c for c in self._evaluate(negative) if c.instrument == "USO")
        assert uso_pos.signals["volatility_gap"] == "positive"
        assert uso_neg.signals["volatility_gap"] == "negative"
        assert uso_pos.edge_score == uso_neg.edge_score

    def test_supply_shock_label_high(self) -> None:
        result = self._evaluate(_make_feature_set([], supply_shock_probability=0.8))
        assert result[0].signals["supply_shock_probability"] == "high"

    def test_supply_shock_label_none(self) -> None:
        result = self._evaluate(_make_feature_set([], tanker_disruption_index=1.0))
        assert result[0].signals["supply_shock_probability"] == "none"

    def test_curve_steepness_label_contango(self) -> None:
        result = self._evaluate(_make_feature_set([], futures_curve_steepness=0.03))
        assert result[0].signals["futures_curve_steepness"] == "contango"

    def test_curve_steepness_label_backwardation(self) -> None:
        result = self._evaluate(_make_feature_set([], futures_curve_steepness=-0.03))
        assert result[0].signals["futures_curve_steepness"] == "backwardation"

    def test_curve_steepness_label_flat(self) -> None:
        result = self._evaluate(_make_feature_set([], supply_shock_probability=1.0))
        assert result[0].signals["futures_curve_steepness"] == "flat"

    def test_feature_set_signals_reach_the_score(self) -> None:
        fs = _make_feature_set(
            [],
            sector_dispersion=0.2,
            supply_shock_probability=0.5,
            futures_curve_steepness=-0.02,
            insider_conviction_score=0.8,
            narrative_velocity=0.6,
            tanker_disruption_index=0.7,
        )
        xom = next(c for c in self._evaluate(fs) if c.instrument == "XOM")
        expected = compute_edge_score(
            "XOM",
            fs,
            OptionStructure.CALL_SPREAD,
            supply_shock_probability=0.5,
            futures_curve_steepness=-0.02,
            insider_conviction_score=0.8,
            narrative_velocity=0.6,
            tanker_disruption_index=0.7,
        )
        assert xom.edge_score == pytest.approx(expected)
        assert expected > 0.0

    def test_instrument_universe_is_tradeable_plus_signal_only(self) -> None:
        """Scope constants stay disjoint and together equal the full universe (#219)."""
        assert not set(TRADEABLE_INSTRUMENTS) & set(SIGNAL_ONLY_INSTRUMENTS)
        assert INSTRUMENTS_IN_SCOPE == TRADEABLE_INSTRUMENTS + SIGNAL_ONLY_INSTRUMENTS
        assert SIGNAL_ONLY_INSTRUMENTS == ["CL=F", "BZ=F"]
        assert TRADEABLE_INSTRUMENTS == ["USO", "XLE", "XOM", "CVX"]
