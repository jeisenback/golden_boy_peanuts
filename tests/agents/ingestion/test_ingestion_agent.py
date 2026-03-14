"""
Unit tests for the Ingestion Agent.

Tests use mocked dependencies (no real DB, no real API calls).
Integration tests belong in test_ingestion_agent_integration.py.

Coverage goal (expand per GitHub Issue):
    - fetch_crude_prices: retry behavior, Pydantic validation, error quarantine
    - fetch_etf_equity_prices: retry behavior, Pydantic validation
    - run_ingestion: partial feed failure returns partial MarketState cleanly
"""

from datetime import UTC, datetime
import logging
from unittest.mock import MagicMock, patch

import pytest

from src.agents.ingestion.ingestion_agent import (
    fetch_crude_prices,
    fetch_etf_equity_prices,
    fetch_options_chain,
    run_ingestion,
)
from src.agents.ingestion.models import InstrumentType, MarketState, OptionRecord, RawPriceRecord


class TestFetchCrudePrices:
    """Tests for fetch_crude_prices() — Alpha Vantage GLOBAL_QUOTE fetcher."""

    def _make_quote_response(self, price: str, volume: str = "123456") -> dict[str, object]:
        return {"Global Quote": {"05. price": price, "06. volume": volume}}

    def test_successful_response_returns_two_records(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns one RawPriceRecord per symbol (CL=F and BZ=F)."""
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "test-key")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = [
            self._make_quote_response("75.50"),
            self._make_quote_response("82.30"),
        ]

        with patch("src.agents.ingestion.ingestion_agent.requests.get", return_value=mock_resp):
            result = fetch_crude_prices()

        assert len(result) == 2
        assert result[0].instrument == "CL=F"
        assert result[1].instrument == "BZ=F"
        assert result[0].source == "alpha_vantage"
        assert result[0].instrument_type == InstrumentType.CRUDE_FUTURES
        assert result[0].price == pytest.approx(75.50)

    def test_timestamp_is_utc_and_shared_across_records(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """timestamp is UTC time of the fetch; both records share the same fetch_time."""
        # using datetime.UTC instead of timezone.utc

        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "test-key")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = [
            self._make_quote_response("75.50"),
            self._make_quote_response("82.30"),
        ]

        with patch("src.agents.ingestion.ingestion_agent.requests.get", return_value=mock_resp):
            result = fetch_crude_prices()

        assert result[0].timestamp.tzinfo == UTC
        assert result[0].timestamp == result[1].timestamp

    def test_malformed_response_missing_price_raises_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ValueError raised when '05. price' is absent; raw response included in message."""
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "test-key")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"Global Quote": {}}  # price key missing

        with patch("src.agents.ingestion.ingestion_agent.requests.get", return_value=mock_resp):
            with patch("time.sleep"):  # suppress tenacity backoff waits
                with pytest.raises(ValueError, match="Malformed Alpha Vantage response"):
                    fetch_crude_prices()

    def test_malformed_response_missing_global_quote_raises_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ValueError raised when 'Global Quote' key is absent entirely."""
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "test-key")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"Note": "API call frequency exceeded"}

        with patch("src.agents.ingestion.ingestion_agent.requests.get", return_value=mock_resp):
            with patch("time.sleep"):
                with pytest.raises(ValueError, match="Malformed Alpha Vantage response"):
                    fetch_crude_prices()

    def test_missing_api_key_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """RuntimeError raised immediately when ALPHA_VANTAGE_API_KEY is not set."""
        monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

        with patch("time.sleep"):
            with pytest.raises(RuntimeError, match="ALPHA_VANTAGE_API_KEY"):
                fetch_crude_prices()


class TestFetchEtfEquityPrices:
    """Tests for fetch_etf_equity_prices() — yfinance price fetcher."""

    def _make_ticker_mock(self, price: float = 75.50, volume: int = 1_234_567) -> MagicMock:
        fast_info = MagicMock()
        fast_info.last_price = price
        fast_info.last_volume = volume
        ticker = MagicMock()
        ticker.fast_info = fast_info
        return ticker

    def test_successful_response_returns_four_records(self) -> None:
        """Returns one RawPriceRecord per symbol (USO, XLE, XOM, CVX)."""
        with patch(
            "src.agents.ingestion.ingestion_agent.yf.Ticker",
            return_value=self._make_ticker_mock(),
        ):
            result = fetch_etf_equity_prices()

        assert len(result) == 4
        assert [r.instrument for r in result] == ["USO", "XLE", "XOM", "CVX"]
        assert all(r.source == "yfinance" for r in result)
        assert all(r.price == pytest.approx(75.50) for r in result)

    def test_instrument_types_set_correctly(self) -> None:
        """USO and XLE are InstrumentType.ETF; XOM and CVX are InstrumentType.EQUITY."""
        with patch(
            "src.agents.ingestion.ingestion_agent.yf.Ticker",
            return_value=self._make_ticker_mock(),
        ):
            result = fetch_etf_equity_prices()

        assert result[0].instrument_type == InstrumentType.ETF  # USO
        assert result[1].instrument_type == InstrumentType.ETF  # XLE
        assert result[2].instrument_type == InstrumentType.EQUITY  # XOM
        assert result[3].instrument_type == InstrumentType.EQUITY  # CVX

    def test_timestamp_is_utc_and_shared_across_records(self) -> None:
        """timestamp is UTC time of the fetch; all records share the same fetch_time."""
        # using datetime.UTC instead of timezone.utc

        with patch(
            "src.agents.ingestion.ingestion_agent.yf.Ticker",
            return_value=self._make_ticker_mock(),
        ):
            result = fetch_etf_equity_prices()

        assert result[0].timestamp.tzinfo == UTC
        assert all(r.timestamp == result[0].timestamp for r in result)

    def test_none_price_raises_value_error(self) -> None:
        """ValueError raised when yfinance returns last_price=None."""
        mock_ticker = self._make_ticker_mock()
        mock_ticker.fast_info.last_price = None

        with patch(
            "src.agents.ingestion.ingestion_agent.yf.Ticker",
            return_value=mock_ticker,
        ):
            with patch("time.sleep"):  # suppress tenacity backoff waits
                with pytest.raises(ValueError, match="Invalid price from yfinance"):
                    fetch_etf_equity_prices()

    def test_yfinance_exception_is_reraised(self) -> None:
        """Exceptions from yfinance are logged and re-raised; caller handles degraded mode."""
        with patch(
            "src.agents.ingestion.ingestion_agent.yf.Ticker",
            side_effect=ConnectionError("network timeout"),
        ):
            with patch("time.sleep"):  # suppress tenacity backoff waits
                with pytest.raises(ConnectionError):
                    fetch_etf_equity_prices()


class TestFetchOptionsChain:
    """Tests for fetch_options_chain() — yfinance options chain fetcher."""

    def _make_row_mock(
        self,
        strike: float = 100.0,
        iv: float = 0.25,
        oi: float = 500.0,
        volume: float = 200.0,
    ) -> MagicMock:
        row = MagicMock()
        row_data = {
            "strike": strike,
            "impliedVolatility": iv,
            "openInterest": oi,
            "volume": volume,
        }
        row.get = lambda key, default=None: row_data.get(key, default)
        row.__getitem__ = lambda self, key: row_data[key]
        return row

    def _make_chain_mock(
        self,
        call_rows: list[MagicMock] | None = None,
        put_rows: list[MagicMock] | None = None,
    ) -> MagicMock:
        if call_rows is None:
            call_rows = [self._make_row_mock()]
        if put_rows is None:
            put_rows = [self._make_row_mock()]

        calls_df = MagicMock()
        calls_df.iterrows.side_effect = lambda: iter(enumerate(call_rows))
        puts_df = MagicMock()
        puts_df.iterrows.side_effect = lambda: iter(enumerate(put_rows))

        chain = MagicMock()
        chain.calls = calls_df
        chain.puts = puts_df
        return chain

    def _make_ticker_mock(
        self,
        expiries: tuple[str, ...] = ("2030-01-17",),
        chain: MagicMock | None = None,
    ) -> MagicMock:
        ticker = MagicMock()
        ticker.options = expiries
        ticker.option_chain.return_value = chain or self._make_chain_mock()
        return ticker

    def test_returns_call_and_put_records(self) -> None:
        """Returns one OptionRecord per contract row (calls + puts) per expiry."""
        ticker = self._make_ticker_mock()

        with patch(
            "src.agents.ingestion.ingestion_agent.yf.Ticker",
            return_value=ticker,
        ):
            result = fetch_options_chain(["USO"])

        # 1 expiry x 1 call + 1 put = 2 records
        assert len(result) == 2
        option_types = {r.option_type for r in result}
        assert option_types == {"call", "put"}
        assert all(r.instrument == "USO" for r in result)
        assert all(r.source == "yfinance" for r in result)
        assert all(r.strike == pytest.approx(100.0) for r in result)

    def test_iv_nan_sets_implied_volatility_to_none(self) -> None:
        """NaN impliedVolatility is mapped to implied_volatility=None in the record."""
        nan_row = self._make_row_mock(iv=float("nan"))
        ticker = self._make_ticker_mock(
            chain=self._make_chain_mock(call_rows=[nan_row], put_rows=[nan_row])
        )

        with patch(
            "src.agents.ingestion.ingestion_agent.yf.Ticker",
            return_value=ticker,
        ):
            result = fetch_options_chain(["USO"])

        assert all(r.implied_volatility is None for r in result)

    def test_option_chain_failure_reraises(self) -> None:
        """Exception from ticker.option_chain() propagates to caller."""
        ticker = MagicMock()
        ticker.options = ("2030-01-17",)
        ticker.option_chain.side_effect = ConnectionError("yfinance unavailable")

        with patch(
            "src.agents.ingestion.ingestion_agent.yf.Ticker",
            return_value=ticker,
        ):
            with patch("time.sleep"):  # suppress tenacity backoff waits
                with pytest.raises(ConnectionError):
                    fetch_options_chain(["USO"])

    def test_no_polygon_key_logs_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Logs a WARNING when POLYGON_API_KEY is not set."""
        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        ticker = self._make_ticker_mock()

        with patch(
            "src.agents.ingestion.ingestion_agent.yf.Ticker",
            return_value=ticker,
        ):
            with caplog.at_level(logging.WARNING, logger="src.agents.ingestion.ingestion_agent"):
                fetch_options_chain(["USO"])

        assert "POLYGON_API_KEY not set" in caplog.text

    def test_multiple_instruments_aggregated(self) -> None:
        """Records from all requested instruments are collected into a single list."""
        ticker = self._make_ticker_mock()

        with patch(
            "src.agents.ingestion.ingestion_agent.yf.Ticker",
            return_value=ticker,
        ):
            result = fetch_options_chain(["USO", "XLE"])

        instruments = [r.instrument for r in result]
        assert instruments.count("USO") == 2  # 1 call + 1 put
        assert instruments.count("XLE") == 2


class TestRunIngestion:
    """Tests for run_ingestion() orchestration function."""

    # Patch targets for all dependencies called by run_ingestion
    _PATCH_CRUDE = "src.agents.ingestion.ingestion_agent.fetch_crude_prices"
    _PATCH_ETF = "src.agents.ingestion.ingestion_agent.fetch_etf_equity_prices"
    _PATCH_OPTIONS = "src.agents.ingestion.ingestion_agent.fetch_options_chain"
    _PATCH_ENGINE = "src.agents.ingestion.ingestion_agent.get_engine"
    _PATCH_WRITE_PRICES = "src.agents.ingestion.ingestion_agent.write_price_records"
    _PATCH_WRITE_OPTIONS = "src.agents.ingestion.ingestion_agent.write_option_records"

    def _make_price_record(self, instrument: str = "CL=F") -> RawPriceRecord:

        return RawPriceRecord(
            instrument=instrument,
            instrument_type=InstrumentType.CRUDE_FUTURES,
            price=75.0,
            volume=1000,
            timestamp=datetime.now(UTC),
            source="test",
        )

    def _make_option_record(self) -> OptionRecord:

        return OptionRecord(
            instrument="USO",
            strike=100.0,
            expiration_date=datetime.now(UTC),
            implied_volatility=0.25,
            open_interest=500,
            volume=200,
            option_type="call",
            timestamp=datetime.now(UTC),
            source="test",
        )

    def test_all_feeds_success_returns_full_market_state(self) -> None:
        """Returns MarketState with all records when every feed succeeds."""
        crude_records = [self._make_price_record("CL=F"), self._make_price_record("BZ=F")]
        etf_records = [self._make_price_record("USO"), self._make_price_record("XLE")]
        option_records = [self._make_option_record()]

        with (
            patch(self._PATCH_CRUDE, return_value=crude_records),
            patch(self._PATCH_ETF, return_value=etf_records),
            patch(self._PATCH_OPTIONS, return_value=option_records),
            patch(self._PATCH_ENGINE, return_value=MagicMock()),
            patch(self._PATCH_WRITE_PRICES, return_value=len(crude_records + etf_records)),
            patch(self._PATCH_WRITE_OPTIONS, return_value=len(option_records)),
        ):
            result = run_ingestion()

        assert isinstance(result, MarketState)
        assert len(result.prices) == 4
        assert len(result.options) == 1
        assert result.ingestion_errors == []

    def test_one_feed_failure_appends_error_and_continues(self) -> None:
        """One failing feed appends to ingestion_errors; other feeds still populate state."""
        etf_records = [self._make_price_record("USO")]
        option_records = [self._make_option_record()]

        with (
            patch(self._PATCH_CRUDE, side_effect=RuntimeError("API key missing")),
            patch(self._PATCH_ETF, return_value=etf_records),
            patch(self._PATCH_OPTIONS, return_value=option_records),
            patch(self._PATCH_ENGINE, return_value=MagicMock()),
            patch(self._PATCH_WRITE_PRICES, return_value=1),
            patch(self._PATCH_WRITE_OPTIONS, return_value=1),
        ):
            result = run_ingestion()

        assert isinstance(result, MarketState)
        assert len(result.prices) == 1  # only ETF records
        assert len(result.options) == 1
        assert len(result.ingestion_errors) == 1
        assert "fetch_crude_prices" in result.ingestion_errors[0]

    def test_all_feeds_failure_returns_empty_state_without_raising(self) -> None:
        """Total feed failure returns empty-but-valid MarketState; never raises."""
        with (
            patch(self._PATCH_CRUDE, side_effect=ConnectionError("unreachable")),
            patch(self._PATCH_ETF, side_effect=ConnectionError("unreachable")),
            patch(self._PATCH_OPTIONS, side_effect=ConnectionError("unreachable")),
            patch(self._PATCH_ENGINE, side_effect=OSError("DATABASE_URL not set")),
        ):
            result = run_ingestion()

        assert isinstance(result, MarketState)
        assert result.prices == []
        assert result.options == []
        assert len(result.ingestion_errors) >= 3
