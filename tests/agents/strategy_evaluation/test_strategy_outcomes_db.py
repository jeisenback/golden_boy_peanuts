"""
Unit tests for strategy_outcomes DB functions:
  write_strategy_outcome() — insert/upsert a single outcome record
  fetch_pending_outcomes() — return candidates past expiration with no outcome

Uses MagicMock to simulate the SQLAlchemy engine/connection without a real DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.agents.ingestion.models import OptionStructure
from src.agents.strategy_evaluation.db import (
    fetch_pending_outcomes,
    write_strategy_outcome,
)
from src.agents.strategy_evaluation.models import StrategyOutcome

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 22, 12, 0, 0, tzinfo=UTC)
_EXPIRY = _NOW + timedelta(days=30)


def _make_outcome(
    candidate_id: int = 1,
    instrument: str = "USO",
    price_at_expiration: float | None = None,
    pct_move: float | None = None,
) -> StrategyOutcome:
    return StrategyOutcome(
        candidate_id=candidate_id,
        instrument=instrument,
        structure=OptionStructure.LONG_STRADDLE,
        generated_at=_NOW,
        expiration_date=_EXPIRY,
        price_at_generation=72.50,
        price_at_expiration=price_at_expiration,
        pct_move=pct_move,
        recorded_at=_NOW,
    )


def _make_engine() -> tuple[MagicMock, MagicMock]:
    """Return (engine, conn) mock pair whose context managers work correctly."""
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


# ---------------------------------------------------------------------------
# write_strategy_outcome
# ---------------------------------------------------------------------------


class TestWriteStrategyOutcome:
    def test_insert_executes_with_correct_row(self) -> None:
        """write_strategy_outcome calls conn.execute once with correct params."""
        engine, conn = _make_engine()
        outcome = _make_outcome(candidate_id=42, instrument="XLE")
        write_strategy_outcome(outcome, engine)
        conn.execute.assert_called_once()
        _, row = conn.execute.call_args.args
        assert row["candidate_id"] == 42
        assert row["instrument"] == "XLE"
        assert row["structure"] == "long_straddle"
        assert row["price_at_generation"] == 72.50
        assert row["price_at_expiration"] is None
        assert row["pct_move"] is None

    def test_nullable_fields_passed_through_when_present(self) -> None:
        """price_at_expiration and pct_move are forwarded when provided."""
        engine, conn = _make_engine()
        outcome = _make_outcome(price_at_expiration=79.10, pct_move=0.091)
        write_strategy_outcome(outcome, engine)
        _, row = conn.execute.call_args.args
        assert row["price_at_expiration"] == pytest.approx(79.10)
        assert row["pct_move"] == pytest.approx(0.091)

    def test_structure_serialized_as_string(self) -> None:
        """OptionStructure enum is stored as its string value, not the enum object."""
        engine, conn = _make_engine()
        outcome = _make_outcome()
        write_strategy_outcome(outcome, engine)
        _, row = conn.execute.call_args.args
        assert isinstance(row["structure"], str)
        assert row["structure"] == "long_straddle"

    def test_db_exception_propagates(self) -> None:
        """SQLAlchemy errors are re-raised after logging."""
        engine = MagicMock()
        engine.begin.return_value.__enter__ = MagicMock(side_effect=RuntimeError("db down"))
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        with pytest.raises(RuntimeError, match="db down"):
            write_strategy_outcome(_make_outcome(), engine)

    def test_uses_begin_for_write_transaction(self) -> None:
        """Write uses engine.begin() (transactional) not engine.connect()."""
        engine, _ = _make_engine()
        write_strategy_outcome(_make_outcome(), engine)
        engine.begin.assert_called_once()
        engine.connect.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_pending_outcomes
# ---------------------------------------------------------------------------


class TestFetchPendingOutcomes:
    def _make_row(
        self,
        candidate_id: int = 1,
        instrument: str = "USO",
    ) -> MagicMock:
        row = MagicMock()
        row.__iter__ = MagicMock(
            return_value=iter(
                [
                    ("candidate_id", candidate_id),
                    ("instrument", instrument),
                    ("structure", "long_straddle"),
                    ("generated_at", _NOW - timedelta(days=40)),
                    ("expiration_date", _NOW - timedelta(days=10)),
                ]
            )
        )
        row.keys = MagicMock(
            return_value=[
                "candidate_id",
                "instrument",
                "structure",
                "generated_at",
                "expiration_date",
            ]
        )
        # Support dict(row) via mapping protocol
        row.__class__ = dict
        return {
            "candidate_id": candidate_id,
            "instrument": instrument,
            "structure": "long_straddle",
            "generated_at": _NOW - timedelta(days=40),
            "expiration_date": _NOW - timedelta(days=10),
        }

    def _make_engine_with_rows(self, rows: list[dict]) -> tuple[MagicMock, MagicMock]:
        engine, conn = _make_engine()
        conn.execute.return_value.mappings.return_value.all.return_value = rows
        return engine, conn

    def test_returns_list_of_dicts(self) -> None:
        """fetch_pending_outcomes returns a list of plain dicts."""
        row = self._make_row(candidate_id=7, instrument="XOM")
        engine, _ = self._make_engine_with_rows([row])
        result = fetch_pending_outcomes(engine, as_of=_NOW)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["candidate_id"] == 7
        assert result[0]["instrument"] == "XOM"

    def test_empty_result_returns_empty_list(self) -> None:
        """No pending candidates → empty list, no exception."""
        engine, _ = self._make_engine_with_rows([])
        result = fetch_pending_outcomes(engine, as_of=_NOW)
        assert result == []

    def test_as_of_forwarded_to_query(self) -> None:
        """The as_of parameter is passed to the SQL query as :as_of."""
        engine, conn = self._make_engine_with_rows([])
        custom_time = datetime(2026, 1, 1, tzinfo=UTC)
        fetch_pending_outcomes(engine, as_of=custom_time)
        _, params = conn.execute.call_args.args
        assert params["as_of"] == custom_time

    def test_default_as_of_is_now(self) -> None:
        """Without explicit as_of, a datetime close to now() is used."""
        engine, conn = self._make_engine_with_rows([])
        before = datetime.now(tz=UTC)
        fetch_pending_outcomes(engine)
        after = datetime.now(tz=UTC)
        _, params = conn.execute.call_args.args
        assert before <= params["as_of"] <= after

    def test_multiple_rows_all_returned(self) -> None:
        """All rows from the query are included in the result."""
        rows = [self._make_row(candidate_id=i) for i in range(1, 4)]
        engine, _ = self._make_engine_with_rows(rows)
        result = fetch_pending_outcomes(engine, as_of=_NOW)
        assert len(result) == 3

    def test_uses_connect_not_begin(self) -> None:
        """Read query uses engine.connect() (read-only), not engine.begin()."""
        engine, _ = self._make_engine_with_rows([])
        fetch_pending_outcomes(engine, as_of=_NOW)
        engine.connect.assert_called_once()
        engine.begin.assert_not_called()

    def test_db_exception_propagates(self) -> None:
        """Connection failures are re-raised to the caller."""
        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(side_effect=RuntimeError("timeout"))
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        with pytest.raises(RuntimeError, match="timeout"):
            fetch_pending_outcomes(engine, as_of=_NOW)
