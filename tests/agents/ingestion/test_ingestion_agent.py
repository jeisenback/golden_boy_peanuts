"""
Unit tests for the Ingestion Agent.

Tests use mocked dependencies (no real DB, no real API calls).
Integration tests belong in test_ingestion_agent_integration.py.

Coverage goal (expand per GitHub Issue):
  - fetch_crude_prices: retry behavior, Pydantic validation, error quarantine
  - fetch_etf_equity_prices: retry behavior, Pydantic validation
  - run_ingestion: partial feed failure returns partial MarketState cleanly
"""

from unittest.mock import MagicMock, patch

import pytest

from src.agents.ingestion.ingestion_agent import fetch_crude_prices, run_ingestion
from src.agents.ingestion.models import InstrumentType, MarketState


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
        from datetime import UTC

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


class TestRunIngestion:
    """Tests for run_ingestion() orchestration function."""

    @pytest.mark.xfail(reason="Not yet implemented", strict=True)
    def test_run_ingestion_returns_market_state(self) -> None:
        """run_ingestion() must return a MarketState instance."""
        result = run_ingestion()
        assert isinstance(result, MarketState)

    @pytest.mark.xfail(reason="Not yet implemented", strict=True)
    def test_run_ingestion_tolerates_single_feed_failure(self) -> None:
        """
        run_ingestion() must not raise if a single feed fails.

        Errors appear in MarketState.ingestion_errors, not as exceptions
        (ESOD Section 6 — degraded-mode output).
        """
        result = run_ingestion()
        assert isinstance(result, MarketState)
        assert isinstance(result.ingestion_errors, list)
