import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from testcontainers.postgres import PostgresContainer

from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.strategy_evaluation.strategy_evaluation_agent import evaluate_strategies


import os

# Run integrations only in CI (local machines often lack testcontainers support).
if not os.environ.get("CI"):
    pytest.skip("Integration tests run in CI only. Set CI=1 to run locally.", allow_module_level=True)


@pytest.mark.integration
def test_strategy_evaluation_writes_candidates_and_golden_range():
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
            sql = (open("db/schema.sql", "r", encoding="utf-8").read())
            # exec_driver_sql executes raw SQL script
            conn.exec_driver_sql(sql)

        # Build a FeatureSet: USO gap=0.1, sector_dispersion=0.1
        snapshot = datetime.now(tz=timezone.utc)
        vg = VolatilityGap(instrument="USO", realized_vol=0.2, implied_vol=0.3, gap=0.1, computed_at=snapshot)
        fs = FeatureSet(snapshot_time=snapshot, volatility_gaps=[vg], sector_dispersion=0.1)

        # Execute evaluation — this should persist candidates to strategy_candidates
        candidates = evaluate_strategies(fs)

        # Query DB to ensure rows were written
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT instrument, structure, edge_score FROM strategy_candidates WHERE instrument = 'USO'")).fetchall()

        assert len(rows) >= 1, "No strategy_candidates rows found for USO"

        # Find long_straddle row
        long_rows = [r for r in rows if r[1] == 'long_straddle']
        assert long_rows, "No long_straddle candidate found for USO"

        edge_score = float(long_rows[0][2])
        # Golden dataset assertion: expect edge_score in [0.38, 0.58]
        assert 0.38 <= edge_score <= 0.58, f"edge_score {edge_score} outside golden range"
