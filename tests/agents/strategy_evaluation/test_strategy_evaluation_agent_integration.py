"""
Integration tests for Strategy Evaluation Agent using Testcontainers (real
Postgres).

- Verifies `evaluate_strategies()` persists candidates to
    `strategy_candidates`.
- Golden dataset validation: USO volatility gap + sector dispersion produce an
    expected candidate and edge_score range.

These tests are marked `@pytest.mark.integration` and are excluded from default
`pytest -m "not integration"` runs.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
import json
import os
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.strategy_evaluation.strategy_evaluation_agent import (
    compute_edge_score,
    evaluate_strategies,
)

# Disable Testcontainers Reaper (Ryuk) on Windows if not available
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

_DDL = """
CREATE TABLE IF NOT EXISTS strategy_candidates (
    id            BIGSERIAL       PRIMARY KEY,
    instrument    TEXT            NOT NULL,
    structure     TEXT            NOT NULL,
    expiration    INTEGER         NOT NULL,
    edge_score    NUMERIC(5,4)    NOT NULL,
    signals       JSONB           NOT NULL,
    generated_at  TIMESTAMPTZ     NOT NULL
);
"""


@pytest.fixture(scope="module")
def pg_engine() -> Generator[Engine, None, None]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:15") as pg:
        engine = create_engine(pg.get_connection_url())
        with engine.begin() as conn:
            conn.execute(text(_DDL))
        yield engine


@pytest.fixture(autouse=True)
def _clean_table(pg_engine: Engine) -> Generator[None, None, None]:
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE strategy_candidates RESTART IDENTITY"))
    yield


def _make_vg(instrument: str, gap: float) -> VolatilityGap:
    return VolatilityGap(
        instrument=instrument,
        realized_vol=0.20,
        implied_vol=0.20 + gap,
        gap=gap,
        computed_at=datetime.now(tz=UTC),
    )


def _make_feature_set(
    gaps: list[VolatilityGap], sector_dispersion: float | None = None
) -> FeatureSet:
    return FeatureSet(
        snapshot_time=datetime.now(tz=UTC),
        volatility_gaps=gaps,
        sector_dispersion=sector_dispersion,
    )


@pytest.mark.integration
def test_evaluate_strategies_persists_candidates(pg_engine: Engine) -> None:
    """Verify evaluate_strategies() persists candidates with correct schema fields.

    AC covered (issue #19):
    - All DB rows have edge_score BETWEEN 0 AND 1
    - instrument, structure, expiration, signals fields present and non-null
    - generated_at is timezone-aware (UTC)
    """
    fs = _make_feature_set([_make_vg("USO", 0.20)], sector_dispersion=0.5)

    with patch(
        "src.agents.strategy_evaluation.strategy_evaluation_agent.get_engine",
        return_value=pg_engine,
    ):
        candidates = evaluate_strategies(fs)

    assert candidates, "expected at least one candidate"

    # Verify DB rows
    with pg_engine.connect() as conn:
        rows = conn.execute(text("""
                SELECT instrument, structure, expiration, edge_score, signals,
                       generated_at
                FROM strategy_candidates
                """)).fetchall()

    assert len(rows) >= 1

    # All rows must satisfy edge_score BETWEEN 0 AND 1
    for row in rows:
        assert 0.0 <= float(row[3]) <= 1.0, f"edge_score {row[3]} out of [0, 1] for {row[0]}"

    instr, _struct, expiration, edge_score, signals_raw, gen_at = rows[0]
    assert instr == "USO"
    assert expiration == 30
    assert 0.0 <= float(edge_score) <= 1.0
    signals = signals_raw if isinstance(signals_raw, dict) else json.loads(signals_raw or "{}")
    assert "volatility_gap" in signals and "sector_dispersion" in signals
    # generated_at must be timezone-aware (UTC)
    assert gen_at.tzinfo is not None, "generated_at must be timezone-aware"


@pytest.mark.integration
def test_golden_dataset_us0_edge_score_range(pg_engine: Engine) -> None:
    """Golden scenario: USO gap ~0.067 and sector_dispersion=0.5 produces
    expected edge_score (~0.39).

    AC covered (issue #19):
    - USO long_straddle candidate generated with edge_score in [0.38, 0.58]
    - signals dict contains volatility_gap='positive' for a positive gap
    - Candidate persisted to DB with edge_score matching in-memory value
    """
    # Use a realistic Phase-1 gap and dispersion that match Feature Generation golden dataset
    gap = 0.0674
    disp = 0.5
    fs = _make_feature_set([_make_vg("USO", gap)], sector_dispersion=disp)

    with patch(
        "src.agents.strategy_evaluation.strategy_evaluation_agent.get_engine",
        return_value=pg_engine,
    ):
        candidates = evaluate_strategies(fs)

    # Find USO long_straddle candidate
    uso = next(
        (c for c in candidates if c.instrument == "USO" and c.structure.value == "long_straddle"),
        None,
    )
    assert uso is not None, "Expected a USO long_straddle candidate"

    # Compute expected score via the same function to avoid magic numbers
    expected = compute_edge_score("USO", fs)
    assert 0.0 <= expected <= 1.0
    # Check expected falls inside the broad acceptance band
    assert 0.38 <= expected <= 0.58

    # signals dict must label a positive gap as 'positive'
    uso_signals = uso.signals if isinstance(uso.signals, dict) else json.loads(uso.signals or "{}")
    assert uso_signals.get("volatility_gap") == "positive", (
        f"expected volatility_gap='positive' for gap={gap}, got {uso_signals.get('volatility_gap')!r}"
    )

    # Also verify DB persist occurred
    with pg_engine.connect() as conn:
        rows = conn.execute(text("""
                SELECT instrument, structure, edge_score
                FROM strategy_candidates
                WHERE instrument = 'USO'
                ORDER BY edge_score DESC
                """)).fetchall()
    assert rows, "Expected persisted USO candidate(s)"
    db_edge = float(rows[0][2])
    assert abs(db_edge - expected) < 1e-3


@pytest.mark.integration
def test_all_signals_none_produces_no_candidates(pg_engine: Engine) -> None:
    """Golden scenario: FeatureSet with no volatility gaps and no sector dispersion
    produces edge_score=0.0 for all instruments, which falls below the minimum
    threshold — so evaluate_strategies() returns an empty list and writes no rows.
    """
    fs = _make_feature_set([], sector_dispersion=None)

    with patch(
        "src.agents.strategy_evaluation.strategy_evaluation_agent.get_engine",
        return_value=pg_engine,
    ):
        candidates = evaluate_strategies(fs)

    assert candidates == [], (
        f"expected no candidates when all signals are None, got {len(candidates)}"
    )

    with pg_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM strategy_candidates")).scalar()
    assert count == 0, f"expected 0 DB rows when all signals None, got {count}"
