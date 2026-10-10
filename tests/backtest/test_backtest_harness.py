"""
Unit tests for scripts/backtest_harness.py (issue #166).

Coverage:
  - replay_pipeline: produces non-empty candidates for high-IV market state
  - load_market_state_from_fixture: loads valid fixture CSV → MarketState
  - missing fixture graceful fallback: no raise, returns empty MarketState → [] candidates
  - write_backtest_report: creates .md file in specified directory
  - COVID fixture assertion: edge_score > 0.60 for long_straddle or call_spread
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
import pathlib as _pathlib
from pathlib import Path
import sys as _sys

import pytest

from src.agents.ingestion.models import (
    InstrumentType,
    MarketState,
    OptionRecord,
    OptionStructure,
    RawPriceRecord,
)
from src.agents.strategy_evaluation.models import StrategyCandidate

# Import harness via sys.path manipulation (scripts/ is not in src/)
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
from scripts.backtest_harness import (  # type: ignore[import]
    _EDGE_SCORE_ASSERTION_THRESHOLD,
    FIXTURES_DIR,
    load_market_state_from_fixture,
    replay_pipeline,
    write_backtest_report,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EVENT_DATE = "2020-03-09"
_SNAP = datetime(2020, 3, 9, tzinfo=UTC)
_EXPIRY = datetime(2020, 4, 17, tzinfo=UTC)


def _make_high_iv_market_state() -> MarketState:
    """Build a MarketState with very high IV — should generate high edge_score candidates."""
    prices = [
        RawPriceRecord(
            instrument="USO",
            instrument_type=InstrumentType.ETF,
            price=4.20,
            timestamp=_SNAP,
            source="test",
        ),
        RawPriceRecord(
            instrument="XLE",
            instrument_type=InstrumentType.ETF,
            price=27.40,
            timestamp=_SNAP,
            source="test",
        ),
        RawPriceRecord(
            instrument="XOM",
            instrument_type=InstrumentType.EQUITY,
            price=38.50,
            timestamp=_SNAP,
            source="test",
        ),
        RawPriceRecord(
            instrument="CVX",
            instrument_type=InstrumentType.EQUITY,
            price=65.00,
            timestamp=_SNAP,
            source="test",
        ),
    ]
    options = [
        OptionRecord(
            instrument="USO",
            strike=4.00,
            expiration_date=_EXPIRY,
            implied_volatility=0.85,  # far above 0.25 baseline → large positive vol gap
            option_type="call",
            timestamp=_SNAP,
            source="test",
        ),
        OptionRecord(
            instrument="XLE",
            strike=27.00,
            expiration_date=_EXPIRY,
            implied_volatility=0.78,
            option_type="call",
            timestamp=_SNAP,
            source="test",
        ),
        OptionRecord(
            instrument="XOM",
            strike=38.00,
            expiration_date=_EXPIRY,
            implied_volatility=0.72,
            option_type="call",
            timestamp=_SNAP,
            source="test",
        ),
        OptionRecord(
            instrument="CVX",
            strike=65.00,
            expiration_date=_EXPIRY,
            implied_volatility=0.68,
            option_type="call",
            timestamp=_SNAP,
            source="test",
        ),
    ]
    return MarketState(snapshot_time=_SNAP, prices=prices, options=options)


def _make_fixture_csv(tmp_path: Path) -> Path:
    """Write a minimal fixture CSV and return its path."""
    fixture = tmp_path / "2020-03-09-test.csv"
    rows = [
        {
            "instrument": "USO",
            "price": "4.20",
            "instrument_type": "etf",
            "implied_vol": "0.85",
            "atm_strike": "4.00",
            "expiration_date": "2020-04-17",
        },
        {
            "instrument": "CL=F",
            "price": "31.13",
            "instrument_type": "crude_futures",
            "implied_vol": "0.90",
            "atm_strike": "31.00",
            "expiration_date": "2020-04-21",
        },
    ]
    with fixture.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return fixture


# ---------------------------------------------------------------------------
# Test: replay produces non-empty candidates
# ---------------------------------------------------------------------------


class TestReplayPipeline:
    def test_high_iv_market_state_produces_candidates(self) -> None:
        """High implied volatility market state yields at least one candidate."""
        ms = _make_high_iv_market_state()
        candidates = replay_pipeline(_EVENT_DATE, ms)
        assert len(candidates) > 0
        assert all(isinstance(c, StrategyCandidate) for c in candidates)

    def test_candidates_sorted_by_edge_score_desc(self) -> None:
        """Candidates are returned in descending edge_score order."""
        ms = _make_high_iv_market_state()
        candidates = replay_pipeline(_EVENT_DATE, ms)
        scores = [c.edge_score for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_high_iv_candidates_exceed_assertion_threshold(self) -> None:
        """Crisis-level IV should produce at least one candidate > 0.60."""
        ms = _make_high_iv_market_state()
        candidates = replay_pipeline(_EVENT_DATE, ms)
        high_edge = [
            c
            for c in candidates
            if c.edge_score >= _EDGE_SCORE_ASSERTION_THRESHOLD
            and c.structure in (OptionStructure.LONG_STRADDLE, OptionStructure.CALL_SPREAD)
        ]
        assert len(high_edge) > 0, (
            f"Expected edge_score > {_EDGE_SCORE_ASSERTION_THRESHOLD} "
            f"but max was {max((c.edge_score for c in candidates), default=0):.4f}"
        )


# ---------------------------------------------------------------------------
# Test: fixture CSV loading
# ---------------------------------------------------------------------------


class TestLoadMarketStateFromFixture:
    def test_valid_fixture_returns_populated_market_state(self, tmp_path: Path) -> None:
        """A valid fixture CSV produces a MarketState with prices and options."""
        fixture = _make_fixture_csv(tmp_path)
        ms = load_market_state_from_fixture(fixture, "2020-03-09")
        assert len(ms.prices) == 2
        assert len(ms.options) == 2
        assert ms.ingestion_errors == []

    def test_snapshot_time_matches_event_date(self, tmp_path: Path) -> None:
        """snapshot_time is parsed from the event_date argument."""
        fixture = _make_fixture_csv(tmp_path)
        ms = load_market_state_from_fixture(fixture, "2020-03-09")
        assert ms.snapshot_time == datetime(2020, 3, 9, tzinfo=UTC)

    def test_instruments_in_market_state(self, tmp_path: Path) -> None:
        """Loaded instruments match the CSV rows."""
        fixture = _make_fixture_csv(tmp_path)
        ms = load_market_state_from_fixture(fixture, "2020-03-09")
        instruments = {p.instrument for p in ms.prices}
        assert "USO" in instruments
        assert "CL=F" in instruments


# ---------------------------------------------------------------------------
# Test: graceful fallback when fixture is missing
# ---------------------------------------------------------------------------


class TestMissingFixtureGracefulFallback:
    def test_missing_fixture_returns_empty_market_state(self, tmp_path: Path) -> None:
        """load_market_state_from_fixture returns an empty MarketState, does not raise."""
        missing = tmp_path / "does_not_exist.csv"
        ms = load_market_state_from_fixture(missing, "2020-03-09")
        assert ms.prices == []
        assert ms.options == []
        assert len(ms.ingestion_errors) > 0

    def test_missing_fixture_replay_returns_empty_list(self, tmp_path: Path) -> None:
        """replay_pipeline on an empty MarketState returns [] without raising."""
        missing = tmp_path / "does_not_exist.csv"
        ms = load_market_state_from_fixture(missing, "2020-03-09")
        candidates = replay_pipeline("2020-03-09", ms)
        assert candidates == []


# ---------------------------------------------------------------------------
# Test: report file written
# ---------------------------------------------------------------------------


class TestWriteBacktestReport:
    def test_report_file_is_created(self, tmp_path: Path) -> None:
        """write_backtest_report creates a .md file in the specified directory."""
        ms = _make_high_iv_market_state()
        candidates = replay_pipeline(_EVENT_DATE, ms)
        report_path = write_backtest_report("2020-03-09", "Test Event", candidates, tmp_path)
        assert report_path.exists()
        assert report_path.suffix == ".md"

    def test_report_contains_event_date(self, tmp_path: Path) -> None:
        """Report markdown includes the event date in the header."""
        ms = _make_high_iv_market_state()
        candidates = replay_pipeline(_EVENT_DATE, ms)
        report_path = write_backtest_report("2020-03-09", "Test Event", candidates, tmp_path)
        content = report_path.read_text(encoding="utf-8")
        assert "2020-03-09" in content

    def test_report_pass_fail_assertion_line(self, tmp_path: Path) -> None:
        """Report contains PASS when high-edge candidates exist."""
        ms = _make_high_iv_market_state()
        candidates = replay_pipeline(_EVENT_DATE, ms)
        report_path = write_backtest_report("2020-03-09", "Test Event", candidates, tmp_path)
        content = report_path.read_text(encoding="utf-8")
        assert "PASS" in content


# ---------------------------------------------------------------------------
# Test: known-event fixtures produce high-edge candidates (integration-lite)
# ---------------------------------------------------------------------------


class TestKnownEventValidations:
    @pytest.mark.skipif(
        not (FIXTURES_DIR / "2020-03-09-covid-crash.csv").exists(),
        reason="fixture CSV not found — run from project root",
    )
    def test_covid_crash_fixture_produces_high_edge_candidates(self) -> None:
        """COVID crash fixture must yield edge_score > 0.60 for straddle/call_spread."""
        fixture = FIXTURES_DIR / "2020-03-09-covid-crash.csv"
        ms = load_market_state_from_fixture(fixture, "2020-03-09")
        candidates = replay_pipeline("2020-03-09", ms)
        high_edge = [
            c
            for c in candidates
            if c.edge_score >= _EDGE_SCORE_ASSERTION_THRESHOLD
            and c.structure in (OptionStructure.LONG_STRADDLE, OptionStructure.CALL_SPREAD)
        ]
        assert len(high_edge) > 0
