"""
Unit tests for src/core/backtest.py — edge score validation harness (#137).

Coverage:
  - _quartile_label: boundary conditions (exact boundary, above, below)
  - _compute_report: quartile binning, hit rate per structure, empty input
  - _fetch_outcome_rows: mocked engine — happy path, DB failure degradation
  - _persist_report: mocked engine — happy path, DB failure degradation
  - run_backtest: mocked engine — returns BacktestReport; degrades gracefully
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.core.backtest import (
    _HIT_THRESHOLD,
    _QUARTILE_LABELS,
    BacktestReport,
    _compute_report,
    _fetch_outcome_rows,
    _persist_report,
    _quartile_label,
    run_backtest,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 6, 1, tzinfo=UTC)
_START = datetime(2024, 3, 3, tzinfo=UTC)


def _row(edge_score: float, structure: str, pct_move: float) -> dict:
    return {"edge_score": edge_score, "structure": structure, "pct_move": pct_move}


def _boundaries() -> list[float]:
    """[p25, p50, p75] for scores [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]."""
    import statistics

    scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    return statistics.quantiles(scores, n=4)


# ---------------------------------------------------------------------------
# _quartile_label
# ---------------------------------------------------------------------------


class TestQuartileLabel:
    def test_at_p25_boundary_is_q1(self) -> None:
        b = [0.25, 0.50, 0.75]
        assert _quartile_label(0.25, b) == "Q1"

    def test_just_above_p25_is_q2(self) -> None:
        b = [0.25, 0.50, 0.75]
        assert _quartile_label(0.26, b) == "Q2"

    def test_at_p50_boundary_is_q2(self) -> None:
        b = [0.25, 0.50, 0.75]
        assert _quartile_label(0.50, b) == "Q2"

    def test_at_p75_boundary_is_q3(self) -> None:
        b = [0.25, 0.50, 0.75]
        assert _quartile_label(0.75, b) == "Q3"

    def test_above_p75_is_q4(self) -> None:
        b = [0.25, 0.50, 0.75]
        assert _quartile_label(0.76, b) == "Q4"

    def test_below_p25_is_q1(self) -> None:
        b = [0.25, 0.50, 0.75]
        assert _quartile_label(0.10, b) == "Q1"

    def test_max_score_is_q4(self) -> None:
        b = [0.25, 0.50, 0.75]
        assert _quartile_label(1.0, b) == "Q4"


# ---------------------------------------------------------------------------
# _compute_report — empty rows
# ---------------------------------------------------------------------------


class TestComputeReportEmpty:
    def test_empty_rows_returns_zero_outcomes(self) -> None:
        report = _compute_report([], _START, _NOW, total_candidates=5)
        assert report.outcomes_recorded == 0
        assert report.total_candidates == 5

    def test_empty_rows_all_quartiles_zero(self) -> None:
        report = _compute_report([], _START, _NOW, total_candidates=0)
        assert all(v == 0.0 for v in report.mean_pct_move_by_score_quartile.values())
        assert set(report.mean_pct_move_by_score_quartile.keys()) == set(_QUARTILE_LABELS)

    def test_empty_rows_hit_rate_empty_dict(self) -> None:
        report = _compute_report([], _START, _NOW, total_candidates=0)
        assert report.hit_rate_by_structure == {}

    def test_period_preserved_when_empty(self) -> None:
        report = _compute_report([], _START, _NOW, total_candidates=0)
        assert report.period_start == _START
        assert report.period_end == _NOW


# ---------------------------------------------------------------------------
# _compute_report — quartile binning
# ---------------------------------------------------------------------------


class TestComputeReportQuartiles:
    def test_q4_mean_exceeds_q1_mean_when_calibrated(self) -> None:
        """Rows where high edge_score correlates with large pct_move."""
        rows = [
            _row(0.10, "long_straddle", 0.01),  # Q1 — small move
            _row(0.20, "long_straddle", 0.02),  # Q1
            _row(0.40, "call_spread", 0.04),  # Q2
            _row(0.50, "call_spread", 0.05),  # Q2/Q3
            _row(0.70, "put_spread", 0.10),  # Q3/Q4
            _row(0.80, "put_spread", 0.15),  # Q4
            _row(0.90, "put_spread", 0.20),  # Q4
            _row(0.95, "put_spread", 0.25),  # Q4
        ]
        report = _compute_report(rows, _START, _NOW, total_candidates=8)
        q4 = report.mean_pct_move_by_score_quartile["Q4"]
        q1 = report.mean_pct_move_by_score_quartile["Q1"]
        assert q4 > q1

    def test_all_quartile_labels_present(self) -> None:
        rows = [_row(float(i) / 8, "long_straddle", 0.03) for i in range(1, 9)]
        report = _compute_report(rows, _START, _NOW, total_candidates=8)
        assert set(report.mean_pct_move_by_score_quartile.keys()) == set(_QUARTILE_LABELS)

    def test_outcomes_recorded_matches_row_count(self) -> None:
        rows = [_row(0.5, "call_spread", 0.06) for _ in range(7)]
        report = _compute_report(rows, _START, _NOW, total_candidates=10)
        assert report.outcomes_recorded == 7

    def test_pct_move_uses_absolute_value(self) -> None:
        """Negative pct_move should contribute positively to mean."""
        rows = [_row(float(i) / 4, "long_straddle", -0.10) for i in range(1, 5)]
        report = _compute_report(rows, _START, _NOW, total_candidates=4)
        for v in report.mean_pct_move_by_score_quartile.values():
            assert v >= 0.0


# ---------------------------------------------------------------------------
# _compute_report — hit rate per structure
# ---------------------------------------------------------------------------


class TestComputeReportHitRate:
    def test_hit_rate_all_above_threshold(self) -> None:
        rows = [_row(float(i) / 4, "long_straddle", _HIT_THRESHOLD + 0.01) for i in range(1, 5)]
        report = _compute_report(rows, _START, _NOW, total_candidates=4)
        assert report.hit_rate_by_structure["long_straddle"] == pytest.approx(1.0)

    def test_hit_rate_none_above_threshold(self) -> None:
        rows = [_row(float(i) / 4, "call_spread", _HIT_THRESHOLD - 0.01) for i in range(1, 5)]
        report = _compute_report(rows, _START, _NOW, total_candidates=4)
        assert report.hit_rate_by_structure["call_spread"] == pytest.approx(0.0)

    def test_hit_rate_partial(self) -> None:
        rows = [
            _row(0.10, "put_spread", _HIT_THRESHOLD + 0.01),  # hit
            _row(0.30, "put_spread", _HIT_THRESHOLD - 0.01),  # miss
            _row(0.60, "put_spread", _HIT_THRESHOLD + 0.01),  # hit
            _row(0.80, "put_spread", _HIT_THRESHOLD - 0.01),  # miss
        ]
        report = _compute_report(rows, _START, _NOW, total_candidates=4)
        assert report.hit_rate_by_structure["put_spread"] == pytest.approx(0.5)

    def test_multiple_structures_independent(self) -> None:
        rows = [
            _row(0.10, "long_straddle", 0.10),
            _row(0.30, "long_straddle", 0.10),
            _row(0.60, "call_spread", 0.01),
            _row(0.80, "call_spread", 0.01),
        ]
        report = _compute_report(rows, _START, _NOW, total_candidates=4)
        assert report.hit_rate_by_structure["long_straddle"] == pytest.approx(1.0)
        assert report.hit_rate_by_structure["call_spread"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _fetch_outcome_rows — DB layer (mocked engine)
# ---------------------------------------------------------------------------


class TestFetchOutcomeRows:
    def _make_engine(self, count_val: int, outcome_rows: list) -> MagicMock:
        engine = MagicMock()
        count_result = MagicMock()
        count_result.fetchone.return_value = (count_val,)

        outcome_result = MagicMock()
        outcome_result.fetchall.return_value = outcome_rows

        conn = MagicMock()
        conn.execute.side_effect = [count_result, outcome_result]
        engine.connect.return_value.__enter__ = lambda s: conn
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        return engine

    def test_returns_total_candidates_and_rows(self) -> None:
        raw_rows = [(0.75, "long_straddle", 0.08), (0.40, "call_spread", 0.03)]
        # connect() is called twice — provide two context managers
        conn1 = MagicMock()
        conn1.execute.return_value.fetchone.return_value = (10,)
        conn2 = MagicMock()
        conn2.execute.return_value.fetchall.return_value = raw_rows

        cm1 = MagicMock()
        cm1.__enter__ = lambda s: conn1
        cm1.__exit__ = MagicMock(return_value=False)
        cm2 = MagicMock()
        cm2.__enter__ = lambda s: conn2
        cm2.__exit__ = MagicMock(return_value=False)

        engine2 = MagicMock()
        engine2.connect.side_effect = [cm1, cm2]

        total, rows = _fetch_outcome_rows(engine2, since=_START)
        assert total == 10
        assert len(rows) == 2
        assert rows[0]["edge_score"] == 0.75
        assert rows[0]["structure"] == "long_straddle"
        assert rows[0]["pct_move"] == 0.08

    def test_db_failure_returns_zero_and_empty(self) -> None:
        engine = MagicMock()
        engine.connect.side_effect = Exception("DB down")
        total, rows = _fetch_outcome_rows(engine, since=_START)
        assert total == 0
        assert rows == []


# ---------------------------------------------------------------------------
# _persist_report — DB layer (mocked engine)
# ---------------------------------------------------------------------------


class TestPersistReport:
    def _make_report(self) -> BacktestReport:
        return BacktestReport(
            period_start=_START,
            period_end=_NOW,
            total_candidates=5,
            outcomes_recorded=3,
            mean_pct_move_by_score_quartile={"Q1": 0.02, "Q2": 0.04, "Q3": 0.06, "Q4": 0.10},
            hit_rate_by_structure={"long_straddle": 0.67},
        )

    def test_happy_path_calls_execute(self) -> None:
        conn = MagicMock()
        cm = MagicMock()
        cm.__enter__ = lambda s: conn
        cm.__exit__ = MagicMock(return_value=False)

        engine = MagicMock()
        engine.begin.return_value = cm

        _persist_report(self._make_report(), lookback_days=90, engine=engine)
        assert conn.execute.call_count == 1

    def test_db_failure_does_not_raise(self) -> None:
        engine = MagicMock()
        engine.begin.side_effect = Exception("DB down")
        # Should not raise — degraded mode
        _persist_report(self._make_report(), lookback_days=90, engine=engine)


# ---------------------------------------------------------------------------
# run_backtest — integration (mocked engine)
# ---------------------------------------------------------------------------


class TestRunBacktest:
    def test_returns_backtest_report(self) -> None:
        raw_rows = [
            (0.10, "long_straddle", 0.02),
            (0.40, "call_spread", 0.04),
            (0.70, "put_spread", 0.08),
            (0.90, "put_spread", 0.15),
        ]

        conn_count = MagicMock()
        conn_count.execute.return_value.fetchone.return_value = (4,)
        conn_outcomes = MagicMock()
        conn_outcomes.execute.return_value.fetchall.return_value = raw_rows

        cm_count = MagicMock()
        cm_count.__enter__ = lambda s: conn_count
        cm_count.__exit__ = MagicMock(return_value=False)

        cm_outcomes = MagicMock()
        cm_outcomes.__enter__ = lambda s: conn_outcomes
        cm_outcomes.__exit__ = MagicMock(return_value=False)

        conn_persist = MagicMock()
        cm_persist = MagicMock()
        cm_persist.__enter__ = lambda s: conn_persist
        cm_persist.__exit__ = MagicMock(return_value=False)

        engine = MagicMock()
        engine.connect.side_effect = [cm_count, cm_outcomes]
        engine.begin.return_value = cm_persist

        report = run_backtest(lookback_days=30, engine=engine)

        assert isinstance(report, BacktestReport)
        assert report.outcomes_recorded == 4
        assert report.total_candidates == 4
        assert set(report.mean_pct_move_by_score_quartile.keys()) == set(_QUARTILE_LABELS)

    def test_degrades_gracefully_on_db_failure(self) -> None:
        engine = MagicMock()
        engine.connect.side_effect = Exception("DB unavailable")
        engine.begin.side_effect = Exception("DB unavailable")

        report = run_backtest(lookback_days=90, engine=engine)

        assert isinstance(report, BacktestReport)
        assert report.outcomes_recorded == 0
        assert report.total_candidates == 0
