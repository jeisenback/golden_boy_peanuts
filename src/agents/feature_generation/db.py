"""
Database read/write for the Feature Generation Agent.
PostgreSQL via SQLAlchemy. Schema TimescaleDB-compatible (ESOD Section 4.3).
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.agents.feature_generation.models import FeatureSet
from src.core.db import get_engine  # noqa: F401

logger = logging.getLogger(__name__)


def read_price_history(
    instrument: str,
    engine: Engine,
    limit: int = 30,
) -> list[float]:
    """
    Read the most recent price records for an instrument from market_prices.

    Args:
        instrument: Ticker symbol to query, e.g. 'USO'.
        engine: SQLAlchemy Engine for the target database.
        limit: Maximum number of records to fetch; defaults to 30 (trading days).

    Returns:
        Prices in chronological order (oldest to newest), up to `limit` records.
        Returns an empty list if no rows match `instrument` — callers must guard
        against this (e.g. compute_volatility_gap skips instruments below _MIN_PRICE_RECORDS).

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on connection or query failure.
    """
    sql = text("""
        SELECT price FROM market_prices
        WHERE instrument = :instrument
        ORDER BY timestamp DESC
        LIMIT :limit
        """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"instrument": instrument, "limit": limit}).fetchall()

    # Rows are newest-first from ORDER BY DESC; reverse for chronological order
    return [float(row[0]) for row in reversed(rows)]


def write_feature_set(feature_set: FeatureSet, engine: Engine) -> None:
    """
    Persist a computed FeatureSet to the feature_sets table.

    volatility_gaps and feature_errors are stored as JSONB. VolatilityGap
    objects are serialized to dicts; datetime fields are converted to ISO strings.

    Args:
        feature_set: Validated FeatureSet to persist.
        engine: SQLAlchemy Engine.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagates on constraint violation or
            connection failure after logging the exception.
    """
    gaps_json = json.dumps(
        [
            {
                "instrument": vg.instrument,
                "realized_vol": vg.realized_vol,
                "implied_vol": vg.implied_vol,
                "gap": vg.gap,
                "computed_at": vg.computed_at.isoformat(),
            }
            for vg in feature_set.volatility_gaps
        ]
    )
    errors_json = json.dumps(feature_set.feature_errors)

    sql = text("""
        INSERT INTO feature_sets
            (snapshot_time, volatility_gaps, sector_dispersion, futures_curve_steepness,
             supply_shock_probability, insider_conviction_score, narrative_velocity,
             tanker_disruption_index, feature_errors, computed_at)
        VALUES
            (:snapshot_time, :volatility_gaps, :sector_dispersion, :futures_curve_steepness,
             :supply_shock_probability, :insider_conviction_score, :narrative_velocity,
             :tanker_disruption_index, :feature_errors, :computed_at)
        """)
    try:
        with engine.begin() as conn:
            conn.execute(
                sql,
                {
                    "snapshot_time": feature_set.snapshot_time,
                    "volatility_gaps": gaps_json,
                    "sector_dispersion": feature_set.sector_dispersion,
                    "futures_curve_steepness": feature_set.futures_curve_steepness,
                    "supply_shock_probability": feature_set.supply_shock_probability,
                    "insider_conviction_score": feature_set.insider_conviction_score,
                    "narrative_velocity": feature_set.narrative_velocity,
                    "tanker_disruption_index": feature_set.tanker_disruption_index,
                    "feature_errors": errors_json,
                    "computed_at": datetime.now(tz=UTC),  # all timestamps stored in UTC
                },
            )
    except Exception:
        logger.exception("write_feature_set failed; FeatureSet not persisted")
        raise

    logger.info(
        "Wrote FeatureSet to feature_sets (snapshot_time=%s, gaps=%d, errors=%d)",
        feature_set.snapshot_time,
        len(feature_set.volatility_gaps),
        len(feature_set.feature_errors),
    )


def read_latest_feature_set(engine: Engine) -> FeatureSet | None:
    """
    Read the most recently computed FeatureSet from the database.

    Returns:
        Most recent FeatureSet, or None if no data exists.

    Raises:
        NotImplementedError: Until implemented.
    """
    sql = text("""
        SELECT snapshot_time, volatility_gaps, sector_dispersion, futures_curve_steepness,
               supply_shock_probability, insider_conviction_score, narrative_velocity,
               tanker_disruption_index, feature_errors, computed_at
        FROM feature_sets
        ORDER BY snapshot_time DESC
        LIMIT 1
        """)

    with engine.connect() as conn:
        row = conn.execute(sql).fetchone()

    if not row:
        return None

    snapshot_time = row[0]
    gaps_raw = row[1]
    sector_dispersion = row[2]
    futures_curve_steepness = row[3]
    supply_shock_probability = row[4]
    insider_conviction_score = row[5]
    narrative_velocity = row[6]
    tanker_disruption_index = row[7]
    errors_raw = row[8]

    # Parse JSONB fields (some DB drivers return Python types directly)
    gaps_list = gaps_raw if isinstance(gaps_raw, list) else json.loads(gaps_raw or "[]")
    errors_list = errors_raw if isinstance(errors_raw, list) else json.loads(errors_raw or "[]")

    from src.agents.feature_generation.models import VolatilityGap

    gaps: list[VolatilityGap] = []
    for g in gaps_list:
        computed_at = g.get("computed_at")
        # computed_at stored as ISO string — parse if necessary
        if isinstance(computed_at, str):
            try:
                computed_at_dt = datetime.fromisoformat(computed_at)
            except Exception:
                logger.warning(
                    "read_latest_feature_set: could not parse computed_at %r; "
                    "substituting now(UTC) — data may be stale",
                    computed_at,
                )
                computed_at_dt = datetime.now(tz=UTC)
        else:
            computed_at_dt = computed_at

        gaps.append(
            VolatilityGap(
                instrument=g.get("instrument"),
                realized_vol=float(g.get("realized_vol")),
                implied_vol=float(g.get("implied_vol")),
                gap=float(g.get("gap")),
                computed_at=computed_at_dt,
            )
        )

    feature_set = FeatureSet(
        snapshot_time=snapshot_time,
        volatility_gaps=gaps,
        sector_dispersion=sector_dispersion,
        futures_curve_steepness=futures_curve_steepness,
        supply_shock_probability=supply_shock_probability,
        insider_conviction_score=insider_conviction_score,
        narrative_velocity=narrative_velocity,
        tanker_disruption_index=tanker_disruption_index,
        feature_errors=errors_list,
    )

    return feature_set
