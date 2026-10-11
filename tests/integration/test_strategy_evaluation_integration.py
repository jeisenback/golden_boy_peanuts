from datetime import UTC, datetime
import os
import pathlib

import pytest
from sqlalchemy import create_engine, text
from testcontainers.postgres import PostgresContainer

from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.strategy_evaluation.strategy_evaluation_agent import (
    evaluate_strategies,
)

# Run integrations only in CI (local machines often lack testcontainers support).
if not os.environ.get("CI"):
    pytest.skip(
        "Integration tests run in CI only. Set CI=1 to run locally.",
        allow_module_level=True,
    )

# Named constants — avoid magic numbers in assertions
USO_REALIZED_VOL: float = 0.2
USO_IMPLIED_VOL: float = 0.3
USO_GAP: float = 0.1
SECTOR_DISPERSION: float = 0.1
SUPPLY_SHOCK_PROBABILITY: float = 0.8
CURVE_STEEPNESS: float = -0.03  # backwardation
EDGE_SCORE_LOW: float = 0.25  # expected 0.2884 (#134 directional scoring, curve weight 0 per #240)
EDGE_SCORE_HIGH: float = 0.33

_SCHEMA_PATH = pathlib.Path(__file__).parents[2] / "db" / "schema.sql"


@pytest.mark.integration
def test_strategy_evaluation_writes_candidates_and_golden_range() -> None:
    """Integration test: run evaluation against real Postgres and assert DB rows.

    Seeds a minimal FeatureSet with supply_shock_probability=0.8, backwardation of -0.03
    and sector_dispersion=0.1, which gives a USO call spread edge_score of about 0.2884:
    net 0.35 * 0.8 = 0.28 (the curve has weight 0, #240), amplified by 1 + 0.30 * 0.1 (#134).
    """
    with PostgresContainer("postgres:15-alpine") as pg:
        db_url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = db_url

        engine = create_engine(db_url)
        with engine.begin() as conn:
            sql = _SCHEMA_PATH.read_text(encoding="utf-8")
            conn.exec_driver_sql(sql)

        snapshot = datetime.now(tz=UTC)
        vg = VolatilityGap(
            instrument="USO",
            realized_vol=USO_REALIZED_VOL,
            implied_vol=USO_IMPLIED_VOL,
            gap=USO_GAP,
            computed_at=snapshot,
        )
        fs = FeatureSet(
            snapshot_time=snapshot,
            volatility_gaps=[vg],
            sector_dispersion=SECTOR_DISPERSION,
            supply_shock_probability=SUPPLY_SHOCK_PROBABILITY,
            futures_curve_steepness=CURVE_STEEPNESS,
        )

        evaluate_strategies(fs)

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT instrument, structure, edge_score"
                    " FROM strategy_candidates WHERE instrument = 'USO'"
                )
            ).fetchall()

        assert len(rows) >= 1, "No strategy_candidates rows found for USO"

        call_rows = [r for r in rows if r[1] == "call_spread"]
        assert call_rows, "No call_spread candidate found for USO"
        assert not [r for r in rows if r[1] == "long_straddle"], "long_straddle is not emitted"

        edge_score = float(call_rows[0][2])
        assert EDGE_SCORE_LOW <= edge_score <= EDGE_SCORE_HIGH, (
            f"edge_score {edge_score} outside golden range"
            f" [{EDGE_SCORE_LOW}, {EDGE_SCORE_HIGH}]"
        )
