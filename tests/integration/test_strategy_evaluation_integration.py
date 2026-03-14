"""Integration tests for strategy evaluation pipeline.

These tests exercise the full strategy evaluation pipeline against a
Postgres database provided by testcontainers. They are intended to run in
CI only; local machines often lack testcontainers support.

Prerequisites:
- `CI=1` set in the environment or CI runner
- Docker available for testcontainers
- `db/schema.sql` present in repository root
"""

from datetime import datetime
import os

import pytest
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer

from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.strategy_evaluation.strategy_evaluation_agent import (
    evaluate_strategies,
)

# Integration tests run only in CI.
if not os.environ.get("CI"):
    pytest.skip(
        "Integration tests run in CI only. Set CI=1 to run locally.",
        allow_module_level=True,
    )
EXPECTED_EDGE_SCORE_MIN = 0.38
EXPECTED_EDGE_SCORE_MAX = 0.58
REALIZED_VOL = 0.2
IMPLIED_VOL = 0.3
GAP = 0.1
SECTOR_DISPERSION = 0.1


def test_strategy_evaluation_writes_candidates_and_golden_range() -> None:
    """Integration test: run evaluation against real Postgres and assert DB rows.

    Seeds a minimal FeatureSet where USO has a volatility gap=0.1 and
    sector_dispersion=0.1 which maps to an expected edge_score of 0.38.
    """
    with PostgresContainer("postgres:15-alpine") as pg:
        db_url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = db_url

        # Apply schema.sql to the test DB
        from sqlalchemy import create_engine

        engine = create_engine(db_url)
        with engine.begin() as conn:
            try:
                sql = open("db/schema.sql", encoding="utf-8").read()
            except FileNotFoundError as exc:
                raise RuntimeError(
                    f"db/schema.sql not found in working directory {os.getcwd()}: {exc}"
                ) from exc
            # exec_driver_sql executes raw SQL script
            try:
                conn.exec_driver_sql(sql)
            except Exception as exc:  # pragma: no cover - integration error path
                raise RuntimeError(f"failed to apply schema.sql: {exc}") from exc

        # Build a FeatureSet: USO gap=0.1, sector_dispersion=0.1
        snapshot = datetime.now(tz=datetime.UTC)
        vg = VolatilityGap(
            instrument="USO",
            realized_vol=REALIZED_VOL,
            implied_vol=IMPLIED_VOL,
            gap=GAP,
            computed_at=snapshot,
        )
        fs = FeatureSet(
            snapshot_time=snapshot,
            volatility_gaps=[vg],
            sector_dispersion=SECTOR_DISPERSION,
        )

        # Execute evaluation — this should persist candidates to strategy_candidates
        candidates = evaluate_strategies(fs)
        assert candidates is not None

        # Query DB to ensure rows were written
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT instrument, structure, edge_score FROM strategy_candidates "
                    "WHERE instrument = 'USO'",
                )
            ).fetchall()

        assert len(rows) >= 1, "No strategy_candidates rows found for USO"

        # Find long_straddle row
        long_rows = [r for r in rows if r[1] == "long_straddle"]
        assert long_rows, "No long_straddle candidate found for USO"

        edge_score = float(long_rows[0][2])
        # Golden dataset assertion: expect edge_score within expected bounds
        assert (
            EXPECTED_EDGE_SCORE_MIN <= edge_score <= EXPECTED_EDGE_SCORE_MAX
        ), f"edge_score {edge_score} outside golden range"
