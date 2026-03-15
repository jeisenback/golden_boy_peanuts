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

from src.agents.feature_generation.feature_generation_agent import (
    compute_sector_dispersion,
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
        timestamp=datetime.now(tz=UTC),
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
        timestamp=datetime.now(tz=UTC),
        source="test",
    )


def _make_market_state(
    instrument: str = "USO",
    price: float = 103.0,
    options: list[OptionRecord] | None = None,
) -> MarketState:
    return MarketState(
        snapshot_time=datetime.now(tz=UTC),
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


# ---------------------------------------------------------------------------
# Helpers shared across TestComputeSectorDispersion
# ---------------------------------------------------------------------------

_SECTOR_TYPES: dict[str, InstrumentType] = {
    "USO": InstrumentType.ETF,
    "XLE": InstrumentType.ETF,
    "XOM": InstrumentType.EQUITY,
    "CVX": InstrumentType.EQUITY,
}


def _make_sector_state(prices: dict[str, float]) -> MarketState:
    """Build a MarketState containing only the given instrument→price entries.

    Raises:
        KeyError: If any key in ``prices`` is not in ``_SECTOR_TYPES``
            ({USO, XLE, XOM, CVX}).
    """
    records = [
        RawPriceRecord(
            instrument=instr,
            instrument_type=_SECTOR_TYPES[instr],
            price=price,
            timestamp=datetime.now(tz=UTC),
            source="test",
        )
        for instr, price in prices.items()
    ]
    return MarketState(snapshot_time=datetime.now(tz=UTC), prices=records, options=[])


class TestComputeSectorDispersion:
    """Tests for compute_sector_dispersion() — CV of XOM/CVX/USO/XLE prices."""

    def test_four_equal_prices_returns_zero(self) -> None:
        """Four identical prices → stdev=0, CV=0.0."""
        state = _make_sector_state({"XOM": 100.0, "CVX": 100.0, "USO": 100.0, "XLE": 100.0})
        assert compute_sector_dispersion(state) == pytest.approx(0.0)

    def test_one_outlier_returns_positive_dispersion(self) -> None:
        """One outlier price raises CV above a detectable threshold."""
        # mean=125, stdev(sample)=50, cv=0.4
        state = _make_sector_state({"XOM": 100.0, "CVX": 100.0, "USO": 100.0, "XLE": 200.0})
        result = compute_sector_dispersion(state)
        assert result is not None
        assert result > 0.1

    def test_cv_formula_matches_expected(self) -> None:
        """CV == stdev(prices) / mean(prices) for a known input."""
        raw = [100.0, 100.0, 100.0, 200.0]
        expected_cv = statistics.stdev(raw) / statistics.mean(raw)
        state = _make_sector_state({"XOM": 100.0, "CVX": 100.0, "USO": 100.0, "XLE": 200.0})
        assert compute_sector_dispersion(state) == pytest.approx(expected_cv)

    def test_cv_capped_at_one(self) -> None:
        """Raw CV > 1.0 is returned as exactly 1.0."""
        # [1, 100, 1, 100]: mean≈50.5, stdev≈57.2, cv≈1.13 > 1.0
        state = _make_sector_state({"XOM": 1.0, "CVX": 100.0, "USO": 1.0, "XLE": 100.0})
        assert compute_sector_dispersion(state) == pytest.approx(1.0)

    def test_fewer_than_two_instruments_returns_none_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Fewer than 2 sector instruments present → None with WARNING logged."""
        state = _make_sector_state({"XOM": 100.0})
        with caplog.at_level(
            logging.WARNING,
            logger="src.agents.feature_generation.feature_generation_agent",
        ):
            result = compute_sector_dispersion(state)
        assert result is None
        assert "Insufficient sector instruments" in caplog.text

    def test_non_sector_instruments_are_ignored(self) -> None:
        """CL=F and BZ=F prices do not influence the sector CV."""
        state = MarketState(
            snapshot_time=datetime.now(tz=UTC),
            prices=[
                RawPriceRecord(
                    instrument="CL=F",
                    instrument_type=InstrumentType.CRUDE_FUTURES,
                    price=9999.0,  # would dominate if included
                    timestamp=datetime.now(tz=UTC),
                    source="test",
                ),
                RawPriceRecord(
                    instrument="XOM",
                    instrument_type=InstrumentType.EQUITY,
                    price=100.0,
                    timestamp=datetime.now(tz=UTC),
                    source="test",
                ),
                RawPriceRecord(
                    instrument="CVX",
                    instrument_type=InstrumentType.EQUITY,
                    price=100.0,
                    timestamp=datetime.now(tz=UTC),
                    source="test",
                ),
            ],
            options=[],
        )
        # Only XOM and CVX are sector instruments; both equal → CV=0.0
        assert compute_sector_dispersion(state) == pytest.approx(0.0)


_PATCH_COMPUTE_VOL_GAP = (
    "src.agents.feature_generation.feature_generation_agent.compute_volatility_gap"
)
_PATCH_COMPUTE_SECTOR = (
    "src.agents.feature_generation.feature_generation_agent.compute_sector_dispersion"
)
_PATCH_COMPUTE_SUPPLY = (
    "src.agents.feature_generation.feature_generation_agent.compute_supply_shock_probability"
)


class TestRunFeatureGeneration:
    """Tests for run_feature_generation() orchestration function."""

    def _base_state(self) -> MarketState:
        return MarketState(snapshot_time=datetime.now(tz=UTC))

    def test_run_feature_generation_returns_feature_set(self) -> None:
        """run_feature_generation() must return a FeatureSet instance."""
        market_state = self._base_state()
        with (
            patch(_PATCH_COMPUTE_VOL_GAP, return_value=[]),
            patch(_PATCH_COMPUTE_SECTOR, return_value=None),
            patch(_PATCH_COMPUTE_SUPPLY, return_value=0.0),
        ):
            result = run_feature_generation(market_state, [])
        assert isinstance(result, FeatureSet)

    def test_successful_signals_populate_feature_set(self) -> None:
        """All successfully computed signals are present in the returned FeatureSet."""
        market_state = self._base_state()
        fake_gaps = [
            VolatilityGap(
                instrument="USO",
                realized_vol=0.20,
                implied_vol=0.30,
                gap=0.10,
                computed_at=datetime.now(tz=UTC),
            )
        ]
        with (
            patch(_PATCH_COMPUTE_VOL_GAP, return_value=fake_gaps),
            patch(_PATCH_COMPUTE_SECTOR, return_value=0.15),
            patch(_PATCH_COMPUTE_SUPPLY, return_value=0.6),
        ):
            result = run_feature_generation(market_state, [])

        assert result.volatility_gaps == fake_gaps
        assert result.sector_dispersion == pytest.approx(0.15)
        assert result.supply_shock_probability == pytest.approx(0.6)
        assert result.feature_errors == []

    def test_partial_signal_failure_does_not_raise(self) -> None:
        """
        If one signal computation fails, run_feature_generation() must return a
        partial FeatureSet with the error in feature_errors, not raise.
        """
        market_state = self._base_state()
        with (
            patch(_PATCH_COMPUTE_VOL_GAP, side_effect=RuntimeError("db down")),
            patch(_PATCH_COMPUTE_SECTOR, return_value=0.05),
            patch(_PATCH_COMPUTE_SUPPLY, return_value=0.2),
        ):
            result = run_feature_generation(market_state, [])

        assert isinstance(result, FeatureSet)
        assert isinstance(result.feature_errors, list)
        assert len(result.feature_errors) == 1
        assert "compute_volatility_gap failed" in result.feature_errors[0]
        assert "db down" in result.feature_errors[0]
        # other signals still computed
        assert result.sector_dispersion == pytest.approx(0.05)
        assert result.supply_shock_probability == pytest.approx(0.2)

    def test_all_signal_failures_recorded_in_feature_errors(self) -> None:
        """All three compute functions failing still returns a valid FeatureSet."""
        market_state = self._base_state()
        with (
            patch(_PATCH_COMPUTE_VOL_GAP, side_effect=RuntimeError("vol fail")),
            patch(_PATCH_COMPUTE_SECTOR, side_effect=ValueError("sector fail")),
            patch(_PATCH_COMPUTE_SUPPLY, side_effect=NotImplementedError("supply fail")),
        ):
            result = run_feature_generation(market_state, [])

        assert isinstance(result, FeatureSet)
        assert len(result.feature_errors) == 3
        assert result.volatility_gaps == []
        assert result.sector_dispersion is None
        assert result.supply_shock_probability is None

    def test_snapshot_time_matches_market_state(self) -> None:
        """FeatureSet.snapshot_time equals market_state.snapshot_time."""
        snap = datetime.now(tz=UTC)
        market_state = MarketState(snapshot_time=snap)
        with (
            patch(_PATCH_COMPUTE_VOL_GAP, return_value=[]),
            patch(_PATCH_COMPUTE_SECTOR, return_value=None),
            patch(_PATCH_COMPUTE_SUPPLY, return_value=0.0),
        ):
            result = run_feature_generation(market_state, [])
        assert result.snapshot_time == snap
