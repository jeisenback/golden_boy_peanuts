"""
Unit tests for the Ingestion Agent.

Tests use mocked dependencies (no real DB, no real API calls).
Integration tests belong in test_ingestion_agent_integration.py.

Coverage goal (expand per GitHub Issue):
  - fetch_crude_prices: retry behavior, Pydantic validation, error quarantine
  - fetch_etf_equity_prices: retry behavior, Pydantic validation
  - run_ingestion: partial feed failure returns partial MarketState cleanly
"""

import pytest

from src.agents.ingestion.ingestion_agent import run_ingestion
from src.agents.ingestion.models import MarketState


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
