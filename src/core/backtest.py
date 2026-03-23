"""
Edge score validation harness — compares predictions against strategy_outcomes (#137).

run_backtest(lookback_days=90) queries strategy_candidates JOIN strategy_outcomes,
groups by edge_score quartile, computes mean absolute pct_move and hit rates per
structure, and returns a BacktestReport. The report is also persisted to a
backtest_reports table (degraded-mode on DB failure).

CLI:
    python -m src.core.backtest --lookback-days 90

Notes:
  - Read-only: never modifies candidates or outcomes.
  - Advisory only: results inform weight recalibration decisions by the human lead.
  - Requires strategy_outcomes table (issue #130) to have populated pct_move values.
    Returns an empty report gracefully if the table does not yet exist.
  - strategy_outcomes table migration: db/migrations/add_strategy_outcomes.sql
  - backtest_reports table migration: db/migrations/add_backtest_reports.sql
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import logging
import statistics
import sys
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.core.db import get_engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum absolute pct_move to count as a "hit" — configurable named constant
_HIT_THRESHOLD: float = 0.05

# Quartile label names (Q1 = lowest edge scores, Q4 = highest)
_QUARTILE_LABELS: list[str] = ["Q1", "Q2", "Q3", "Q4"]


# ---------------------------------------------------------------------------
# BacktestReport model
# ---------------------------------------------------------------------------


class BacktestReport(BaseModel):
    """
    Summary of edge score predictive accuracy over a historical lookback window.

    mean_pct_move_by_score_quartile: average absolute price move per quartile of
        edge_score (Q1 = lowest scores, Q4 = highest).  A well-calibrated edge
        score should show Q4 > Q3 > Q2 > Q1.

    hit_rate_by_structure: fraction of candidates per structure where
        abs(pct_move) > _HIT_THRESHOLD (5% move).
    """

    period_start: datetime = Field(..., description="Start of the lookback window (UTC)")
    period_end: datetime = Field(..., description="End of the lookback window (UTC)")
    total_candidates: int = Field(..., ge=0, description="Candidates generated in window")
    outcomes_recorded: int = Field(..., ge=0, description="Candidates with resolved pct_move")
    mean_pct_move_by_score_quartile: dict[str, float] = Field(
        ...,
        description="Q1-Q4 -> mean absolute pct_move; Q4 should exceed Q1 if predictive",
    )
    hit_rate_by_structure: dict[str, float] = Field(
        ...,
        description="structure → fraction of candidates with abs(pct_move) > _HIT_THRESHOLD",
    )


# ---------------------------------------------------------------------------
# Pure-logic helpers (no DB dependency — fully unit-testable)
# ---------------------------------------------------------------------------


def _quartile_label(score: float, boundaries: list[float]) -> str:
    """
    Assign a Q1/Q2/Q3/Q4 label for a given edge_score.

    Args:
        score:      edge_score value to classify.
        boundaries: [p25, p50, p75] computed by statistics.quantiles(scores, n=4).

    Returns:
        "Q1" if score ≤ p25, "Q2" if ≤ p50, "Q3" if ≤ p75, else "Q4".
    """
    if score <= boundaries[0]:
        return "Q1"
    if score <= boundaries[1]:
        return "Q2"
    if score <= boundaries[2]:
        return "Q3"
    return "Q4"


def _compute_report(
    rows: list[dict[str, Any]],
    period_start: datetime,
    period_end: datetime,
    total_candidates: int,
) -> BacktestReport:
    """
    Build a BacktestReport from a list of outcome rows.

    Args:
        rows:             List of dicts with keys 'edge_score', 'structure', 'pct_move'.
        period_start:     Start of the lookback window.
        period_end:       End of the lookback window.
        total_candidates: Total candidates generated in window (may exceed len(rows)
            if some outcomes are not yet resolved).

    Returns:
        BacktestReport with quartile moves and hit rates.  Returns all-zero values
        when rows is empty (no outcomes recorded yet).
    """
    if not rows:
        return BacktestReport(
            period_start=period_start,
            period_end=period_end,
            total_candidates=total_candidates,
            outcomes_recorded=0,
            mean_pct_move_by_score_quartile=dict.fromkeys(_QUARTILE_LABELS, 0.0),
            hit_rate_by_structure={},
        )

    scores = [float(r["edge_score"]) for r in rows]

    # Compute [p25, p50, p75] quartile boundaries.
    # statistics.quantiles requires n+1 data points for n quantiles (n=4 → 4 points).
    # Fall back to equal-width bins for small datasets.
    if len(scores) >= 4:
        boundaries: list[float] = statistics.quantiles(scores, n=4)
    else:
        lo, hi = min(scores), max(scores)
        step = (hi - lo) / 4 if hi > lo else 0.25
        boundaries = [lo + step, lo + 2 * step, lo + 3 * step]

    quartile_moves: dict[str, list[float]] = {q: [] for q in _QUARTILE_LABELS}
    structure_hits: dict[str, list[bool]] = {}

    for row in rows:
        score = float(row["edge_score"])
        structure = str(row["structure"])
        pct_move = float(row["pct_move"])

        label = _quartile_label(score, boundaries)
        quartile_moves[label].append(abs(pct_move))
        structure_hits.setdefault(structure, []).append(abs(pct_move) > _HIT_THRESHOLD)

    mean_by_quartile: dict[str, float] = {
        q: statistics.mean(moves) if moves else 0.0 for q, moves in quartile_moves.items()
    }
    hit_rates: dict[str, float] = {
        struct: sum(hits) / len(hits) for struct, hits in structure_hits.items()
    }

    return BacktestReport(
        period_start=period_start,
        period_end=period_end,
        total_candidates=total_candidates,
        outcomes_recorded=len(rows),
        mean_pct_move_by_score_quartile=mean_by_quartile,
        hit_rate_by_structure=hit_rates,
    )


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def _fetch_outcome_rows(
    engine: Engine,
    since: datetime,
) -> tuple[int, list[dict[str, Any]]]:
    """
    Query strategy_candidates JOIN strategy_outcomes for the lookback window.

    Returns:
        (total_candidates, outcome_rows) where outcome_rows contains only
        candidates with a resolved pct_move.  Returns (0, []) on DB failure
        so run_backtest() degrades gracefully when tables don't exist yet.
    """
    count_sql = text("SELECT COUNT(*) FROM strategy_candidates WHERE generated_at >= :since")
    total_candidates = 0
    try:
        with engine.connect() as conn:
            row = conn.execute(count_sql, {"since": since}).fetchone()
            total_candidates = int(row[0]) if row else 0
    except Exception:
        logger.warning("_fetch_outcome_rows: could not count strategy_candidates; using 0")

    outcomes_sql = text("""
        SELECT
            sc.edge_score,
            sc.structure,
            so.pct_move
        FROM strategy_candidates sc
        JOIN strategy_outcomes so ON so.candidate_id = sc.id
        WHERE sc.generated_at >= :since
          AND so.pct_move IS NOT NULL
        ORDER BY sc.edge_score ASC
        """)
    rows: list[dict[str, Any]] = []
    try:
        with engine.connect() as conn:
            result = conn.execute(outcomes_sql, {"since": since})
            rows = [
                {"edge_score": r[0], "structure": r[1], "pct_move": r[2]} for r in result.fetchall()
            ]
    except Exception:
        logger.warning(
            "_fetch_outcome_rows: strategy_outcomes query failed — "
            "table may not exist yet; returning empty outcome set"
        )

    return total_candidates, rows


def _persist_report(
    report: BacktestReport,
    lookback_days: int,
    engine: Engine,
) -> None:
    """
    Persist a BacktestReport to backtest_reports (degraded-mode on failure).

    Requires backtest_reports table from db/migrations/add_backtest_reports.sql.
    Logs a WARNING and returns without raising if the table doesn't exist yet.
    """
    sql = text("""
        INSERT INTO backtest_reports
            (period_start, period_end, lookback_days, total_candidates,
             outcomes_recorded, report_json, generated_at)
        VALUES
            (:period_start, :period_end, :lookback_days, :total_candidates,
             :outcomes_recorded, :report_json, :generated_at)
        """)
    params: dict[str, Any] = {
        "period_start": report.period_start,
        "period_end": report.period_end,
        "lookback_days": lookback_days,
        "total_candidates": report.total_candidates,
        "outcomes_recorded": report.outcomes_recorded,
        "report_json": json.dumps(report.model_dump(mode="json")),
        "generated_at": datetime.now(tz=UTC),
    }
    try:
        with engine.begin() as conn:
            conn.execute(sql, params)
        logger.info("_persist_report: backtest report written to backtest_reports")
    except Exception:
        logger.warning(
            "_persist_report: could not persist to backtest_reports — "
            "table may not exist yet; report still returned to caller"
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_backtest(
    lookback_days: int = 90,
    engine: Engine | None = None,
) -> BacktestReport:
    """
    Compare edge_score predictions against recorded strategy_outcomes.

    Queries strategy_candidates JOIN strategy_outcomes for candidates generated
    within the last `lookback_days` that have a resolved pct_move. Groups by
    edge_score quartile to measure mean absolute price move (Q4 should exceed Q1
    if edge_score has predictive value). Computes hit rates per structure.

    The report is persisted to backtest_reports in degraded-mode (log-and-continue
    on failure) so that a missing table never suppresses the return value.

    Args:
        lookback_days: Number of calendar days to look back from now. Default: 90.
        engine:        SQLAlchemy Engine. Default: get_engine() from DATABASE_URL.

    Returns:
        BacktestReport — all-zero values if no outcomes are recorded yet.
    """
    if engine is None:
        engine = get_engine()

    period_end = datetime.now(tz=UTC)
    period_start = period_end - timedelta(days=lookback_days)

    total_candidates, rows = _fetch_outcome_rows(engine, since=period_start)
    report = _compute_report(rows, period_start, period_end, total_candidates)

    logger.info(
        "run_backtest: lookback=%dd total_candidates=%d outcomes_recorded=%d",
        lookback_days,
        report.total_candidates,
        report.outcomes_recorded,
    )

    _persist_report(report, lookback_days, engine)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and run the backtest."""
    parser = argparse.ArgumentParser(
        description="Edge score validation harness — compares predictions vs. outcomes"
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=90,
        help="Number of days to look back from now (default: 90)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    report = run_backtest(lookback_days=args.lookback_days)
    print(json.dumps(report.model_dump(mode="json"), indent=2))  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(_main())
