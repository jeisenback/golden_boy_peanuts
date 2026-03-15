import os
import pathlib
from datetime import datetime, timezone

import pytest

# Run integrations only in CI (local machines often lack testcontainers support).
# Guard must come before testcontainers import so ImportError doesn't fire first.
if not os.environ.get("CI"):
    pytest.skip("Integration tests run in CI only. Set CI=1 to run locally.", allow_module_level=True)

from sqlalchemy import create_engine, text  # noqa: E402

from testcontainers.postgres import PostgresContainer  # noqa: E402

from src.agents.feature_generation.models import FeatureSet, VolatilityGap  # noqa: E402
from src.agents.strategy_evaluation.strategy_evaluation_agent import evaluate_strategies  # noqa: E402

# Named constants — avoid magic numbers in assertions
USO_REALIZED_VOL: float = 0.2
USO_IMPLIED_VOL: float = 0.3
USO_GAP: float = 0.1
SECTOR_DISPERSION: float = 0.1
EDGE_SCORE_LOW: float = 0.38
EDGE_SCORE_HIGH: float = 0.58

_SCHEMA_PATH = pathlib.Path(__file__).parents[2] / "db" / "schema.sql"


@pytest.mark.integration
def test_strategy_evaluation_writes_candidates_and_golden_range() -> None:
    """Integration test: run evaluation against real Postgres and assert DB rows.

    Seeds a minimal FeatureSet where USO has a volatility gap=0.1 and
    sector_dispersion=0.1 which maps to an expected edge_score in [0.38, 0.58].
    """
    with PostgresContainer("postgres:15-alpine") as pg:
        db_url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = db_url

        engine = create_engine(db_url)
        with engine.begin() as conn:
            sql = _SCHEMA_PATH.read_text(encoding="utf-8")
            conn.exec_driver_sql(sql)

        snapshot = datetime.now(tz=timezone.utc)
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

        long_rows = [r for r in rows if r[1] == "long_straddle"]
        assert long_rows, "No long_straddle candidate found for USO"

        edge_score = float(long_rows[0][2])
        assert EDGE_SCORE_LOW <= edge_score <= EDGE_SCORE_HIGH, (
            f"edge_score {edge_score} outside golden range [{EDGE_SCORE_LOW}, {EDGE_SCORE_HIGH}]"
        )
