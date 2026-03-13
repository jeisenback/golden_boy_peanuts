"""
Unit tests for the Feature Generation Agent.

Coverage goal (expand per GitHub Issue):
  - run_feature_generation: returns FeatureSet
  - compute_supply_shock_probability: returns float in [0.0, 1.0]
  - compute_volatility_gap: returns VolatilityGap with correct gap calculation
  - Partial signal failure populates feature_errors, does not raise
"""

from datetime import UTC, datetime
import logging
import math
import statistics
from unittest.mock import MagicMock, patch

import pytest

from src.agents.event_detection.models import DetectedEvent
from src.agents.feature_generation.feature_generation_agent import (
    compute_volatility_gap,
    run_feature_generation,
)
from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.ingestion.models import InstrumentType, MarketState, OptionRecord, RawPriceRecord

# ---------------------------------------------------------------------------
# Helpers shared across TestComputeVolatilityGap
# ---------------------------------------------------------------------------

_KNOWN_PRICES: list[float] = [
    100.0,
    101.0,
    99.0,
    102.0,
    100.0,
    103.0,
    101.0,
    104.0,
    102.0,
    105.0,
    103.0,
]  # 11 prices → 10 log returns (> _MIN_PRICE_RECORDS=10)


def _expected_realized_vol(prices: list[float]) -> float:
    """Compute expected realized vol using the same formula as the agent."""
    log_returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
    return statistics.stdev(log_returns) * math.sqrt(252)


def _make_price_record(instrument: str = "USO", price: float = 103.0) -> RawPriceRecord:
    return RawPriceRecord(
        instrument=instrument,
        instrument_type=InstrumentType.ETF,
        price=price,
        timestamp=datetime.now(UTC),
        source="test",
    )


def _make_option(
    instrument: str = "USO",
    strike: float = 103.0,
    iv: float | None = 0.30,
    expiry: str = "2030-01-17",
) -> OptionRecord:
    return OptionRecord(
        instrument=instrument,
        strike=strike,
        expiration_date=datetime.strptime(expiry, "%Y-%m-%d").replace(tzinfo=UTC),
        implied_volatility=iv,
        option_type="call",
        timestamp=datetime.now(UTC),
        source="test",
    )


def _make_market_state(
    instrument: str = "USO",
    price: float = 103.0,
    options: list[OptionRecord] | None = None,
) -> MarketState:
    return MarketState(
        snapshot_time=datetime.now(UTC),
        prices=[_make_price_record(instrument, price)],
        options=options if options is not None else [_make_option(instrument)],
    )


class TestComputeVolatilityGap:
    """Tests for compute_volatility_gap() — realized vs. implied vol computation."""

    _PATCH_ENGINE = "src.agents.feature_generation.feature_generation_agent.get_engine"
    _PATCH_READ = "src.agents.feature_generation.feature_generation_agent.read_price_history"

    def test_returns_volatility_gap_for_each_valid_instrument(self) -> None:
        """Returns one VolatilityGap per instrument with sufficient data and options."""
        market_state = _make_market_state()

        with (
            patch(self._PATCH_ENGINE, return_value=MagicMock()),
            patch(self._PATCH_READ, return_value=_KNOWN_PRICES),
        ):
            result = compute_volatility_gap(market_state)

        assert len(result) == 1
        assert isinstance(result[0], VolatilityGap)
        assert result[0].instrument == "USO"
        assert result[0].implied_vol == pytest.approx(0.30)
        assert result[0].gap == pytest.approx(result[0].implied_vol - result[0].realized_vol)

    def test_realized_vol_calculation_matches_formula(self) -> None:
        """realized_vol equals stdev(log returns) x sqrt(252) for the known price series."""
        expected = _expected_realized_vol(_KNOWN_PRICES)
        market_state = _make_market_state()

        with (
            patch(self._PATCH_ENGINE, return_value=MagicMock()),
            patch(self._PATCH_READ, return_value=_KNOWN_PRICES),
        ):
            result = compute_volatility_gap(market_state)

        assert result[0].realized_vol == pytest.approx(expected)
        assert result[0].gap == pytest.approx(0.30 - expected)

    def test_atm_strike_selection_picks_closest_to_current_price(self) -> None:
        """ATM option is the one with strike nearest to the instrument's current price."""
        current_price = 100.0
        far_opt = _make_option(strike=92.0, iv=0.40)  # |100 - 92| = 8
        close_opt = _make_option(strike=101.0, iv=0.22)  # |100 - 101| = 1 — closer
        market_state = _make_market_state(price=current_price, options=[far_opt, close_opt])

        with (
            patch(self._PATCH_ENGINE, return_value=MagicMock()),
            patch(self._PATCH_READ, return_value=_KNOWN_PRICES),
        ):
            result = compute_volatility_gap(market_state)

        assert len(result) == 1
        assert result[0].implied_vol == pytest.approx(0.22)  # close_opt's IV

    def test_fewer_than_10_price_records_skips_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Instruments with < 10 DB price records are skipped; a WARNING is logged."""
        market_state = _make_market_state()

        with (
            patch(self._PATCH_ENGINE, return_value=MagicMock()),
            patch(self._PATCH_READ, return_value=[100.0, 101.0, 99.0]),  # only 3 records
            caplog.at_level(
                logging.WARNING,
                logger="src.agents.feature_generation.feature_generation_agent",
            ),
        ):
            result = compute_volatility_gap(market_state)

        assert result == []
        assert "Insufficient price history" in caplog.text

    def test_no_options_for_instrument_skips_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Instruments without options in market_state are skipped; a WARNING is logged."""
        market_state = _make_market_state(options=[])  # no options at all

        with (
            patch(self._PATCH_ENGINE, return_value=MagicMock()),
            caplog.at_level(
                logging.WARNING,
                logger="src.agents.feature_generation.feature_generation_agent",
            ),
        ):
            result = compute_volatility_gap(market_state)

        assert result == []
        assert "No options data" in caplog.text

    def test_atm_option_with_none_iv_skips_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ATM option whose implied_volatility is None causes the instrument to be skipped."""
        market_state = _make_market_state(options=[_make_option(iv=None)])

        with (
            patch(self._PATCH_ENGINE, return_value=MagicMock()),
            patch(self._PATCH_READ, return_value=_KNOWN_PRICES),
            caplog.at_level(
                logging.WARNING,
                logger="src.agents.feature_generation.feature_generation_agent",
            ),
        ):
            result = compute_volatility_gap(market_state)

        assert result == []
        assert "no implied volatility" in caplog.text


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
