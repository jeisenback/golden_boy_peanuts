#!/usr/bin/env python3
"""
Write one pipeline run's candidates to a dated JSON snapshot (issue #218).

The nightly workflow runs against an ephemeral Postgres, so nothing survives the job.
This module turns the run's StrategyCandidate list, plus the latest stored price per
instrument, into data/candidates/YYYY-MM-DD.json. The workflow then publishes that file
to the `data` branch (scripts/publish_candidate_snapshot.sh).

Design notes:
  - Re-running on the same UTC date overwrites that date's file.
  - A run with zero candidates still writes a file with an empty list, so a missing file
    means the run failed, not that it found nothing.
  - price_at_generation is the latest market_prices row per instrument, or null when the
    instrument has no stored price. It is read from the DB, not from run_pipeline().

Usage (inside the pipeline process):
    from scripts.write_candidate_snapshot import write_snapshot
    write_snapshot(candidates)
"""

from __future__ import annotations

from datetime import UTC, date, datetime
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

from src.agents.strategy_evaluation.models import StrategyCandidate

SNAPSHOT_DIR = Path("data/candidates")

logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    """Return value in UTC; a naive datetime is taken to already be UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def serialize_snapshot(
    candidates: list[StrategyCandidate],
    prices: dict[str, float],
    run_date: date,
) -> dict[str, Any]:
    """
    Build the JSON-ready snapshot for one run.

    Args:
        candidates: The run's candidates, in the order given.
        prices:     Latest stored price per instrument; instruments without one get null.
        run_date:   UTC date of the run, recorded in the snapshot.

    Returns:
        Dict with run_date and a candidates list. Each candidate carries instrument,
        structure, expiration, edge_score, signals, generated_at (UTC ISO 8601) and
        price_at_generation.
    """
    return {
        "run_date": run_date.isoformat(),
        "candidates": [
            {
                "instrument": c.instrument,
                "structure": c.structure.value,
                "expiration": c.expiration,
                "edge_score": c.edge_score,
                "signals": dict(c.signals),
                "generated_at": _as_utc(c.generated_at).isoformat(),
                "price_at_generation": prices.get(c.instrument),
            }
            for c in candidates
        ],
    }


def fetch_latest_prices(engine: Engine, instruments: list[str]) -> dict[str, float]:
    """Return the most recent market_prices price for each of the given instruments."""
    if not instruments:
        return {}
    query = text("""
        SELECT m.instrument, m.price
        FROM market_prices AS m
        JOIN (
            SELECT instrument, MAX(timestamp) AS latest
            FROM market_prices
            WHERE instrument IN :instruments
            GROUP BY instrument
        ) AS l ON l.instrument = m.instrument AND l.latest = m.timestamp
        """).bindparams(bindparam("instruments", expanding=True))
    with engine.connect() as conn:
        rows = conn.execute(query, {"instruments": sorted(set(instruments))}).all()
    return {str(instrument): float(price) for instrument, price in rows}


def write_snapshot(
    candidates: list[StrategyCandidate],
    *,
    engine: Engine | None = None,
    out_dir: Path = SNAPSHOT_DIR,
    now: datetime | None = None,
) -> Path:
    """
    Write data/candidates/YYYY-MM-DD.json for this run and return its path.

    Args:
        candidates: Output of run_pipeline().
        engine:     Database engine for price lookup; defaults to the DATABASE_URL engine.
        out_dir:    Directory for snapshot files.
        now:        Run time override for tests; defaults to the current UTC time.

    Raises:
        RuntimeError: if no engine is given and DATABASE_URL is not set.
    """
    run_time = _as_utc(now) if now is not None else datetime.now(tz=UTC)
    if engine is None:
        from src.core.db import get_engine

        engine = get_engine()

    prices = fetch_latest_prices(engine, [c.instrument for c in candidates])
    snapshot = serialize_snapshot(candidates, prices, run_time.date())

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run_time.date().isoformat()}.json"
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info("Wrote %d candidate(s) to %s", len(candidates), path)
    return path
