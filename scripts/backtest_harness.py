#!/usr/bin/env python3
"""
backtest_harness.py — Historical pipeline replay (issue #166).

Runs the full strategy evaluation pipeline against injected historical
MarketState objects backed by fixture CSVs. Validates edge scores against
three known energy volatility events where the correct trade was obvious in
hindsight:

  - COVID crude crash:        2020-03-09 (WTI -26% in a single day)
  - Ukraine invasion:         2022-02-24 (Brent +8%, massive vol spike)
  - Houthi shipping attack:   2023-12-18 (tanker rerouting signal)

Entry point:
  replay_pipeline(event_date, market_state) -> list[StrategyCandidate]

Fixture loader:
  load_market_state_from_fixture(fixture_path, event_date) -> MarketState

Report writer:
  write_backtest_report(event_date, event_name, candidates, report_dir) -> Path

ESOD constraints:
  - No DB writes to live tables (strategy_candidates, feature_sets).
  - All public functions carry full type hints.
  - No langchain.* imports.
"""

from __future__ import annotations

import csv
import logging
import statistics
from datetime import UTC, datetime
from pathlib import Path

from src.agents.feature_generation.models import FeatureSet, VolatilityGap
from src.agents.ingestion.models import (
    InstrumentType,
    MarketState,
    OptionRecord,
    OptionStructure,
    RawPriceRecord,
)
from src.agents.strategy_evaluation.models import StrategyCandidate
from src.agents.strategy_evaluation.strategy_evaluation_agent import (
    INSTRUMENTS_IN_SCOPE,
    compute_edge_score,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default fixture directory — relative to project root
FIXTURES_DIR: Path = Path("backtests/fixtures")

# Default report output directory
REPORTS_DIR: Path = Path("docs/backtest_reports")

# Baseline long-term realized volatility per instrument (annualised).
# Used when historical price series are not available for the replay window.
# Source: 5-year pre-crisis trailing average, approximate.
_BASELINE_REALIZED_VOL: dict[str, float] = {
    "USO": 0.25,
    "XLE": 0.22,
    "XOM": 0.20,
    "CVX": 0.19,
    "CL=F": 0.30,
    "BZ=F": 0.28,
}
_DEFAULT_REALIZED_VOL: float = 0.25  # fallback for instruments not in the map

# Phase 1 structures evaluated per instrument
_REPLAY_STRUCTURES: list[OptionStructure] = [
    OptionStructure.LONG_STRADDLE,
    OptionStructure.CALL_SPREAD,
    OptionStructure.PUT_SPREAD,
]

# Target expiration in calendar days (mirrors live pipeline Phase 1 default)
_DEFAULT_EXPIRATION_DAYS: int = 30

# Minimum edge score to include a candidate in replay results
_MIN_EDGE_SCORE: float = 0.10

# Assertion threshold used in run_event_validations()
_EDGE_SCORE_ASSERTION_THRESHOLD: float = 0.60

# Instruments that constitute the 'sector' for dispersion measurement
_SECTOR_INSTRUMENTS: frozenset[str] = frozenset({"XOM", "CVX", "USO", "XLE"})

# Known events: (fixture_stem, event_name)
KNOWN_EVENTS: list[tuple[str, str]] = [
    ("2020-03-09-covid-crash", "COVID Crude Crash — 2020-03-09"),
    ("2022-02-24-ukraine-invasion", "Ukraine Invasion — 2022-02-24"),
    ("2023-12-18-houthi-disruptions", "Houthi Shipping Disruptions — 2023-12-18"),
]


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


def load_market_state_from_fixture(
    fixture_path: Path,
    event_date: str,
) -> MarketState:
    """
    Load a fixture CSV and build a MarketState for the given event date.

    The fixture CSV must contain the columns:
      instrument, price, instrument_type, implied_vol, atm_strike, expiration_date

    Each row produces one RawPriceRecord and one OptionRecord (ATM call) so
    that replay_pipeline() has both price and implied-volatility data.

    Args:
        fixture_path: Path to the fixture CSV file.
        event_date:   Date string in YYYY-MM-DD format (used as snapshot_time).

    Returns:
        MarketState populated from the fixture. Returns an empty MarketState
        (with a WARNING) if the file is missing or unreadable — allows
        replay_pipeline() to return [] gracefully rather than raising.
    """
    snapshot_time = datetime.strptime(event_date, "%Y-%m-%d").replace(tzinfo=UTC)

    if not fixture_path.exists():
        logger.warning(
            "load_market_state_from_fixture: fixture not found at %s — "
            "returning empty MarketState",
            fixture_path,
        )
        return MarketState(
            snapshot_time=snapshot_time,
            ingestion_errors=[f"fixture not found: {fixture_path}"],
        )

    prices: list[RawPriceRecord] = []
    options: list[OptionRecord] = []
    errors: list[str] = []

    try:
        with fixture_path.open(newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                instrument = row["instrument"].strip()
                try:
                    price_val = float(row["price"])
                    instr_type_raw = row["instrument_type"].strip()
                    implied_vol_val = float(row["implied_vol"])
                    atm_strike_val = float(row["atm_strike"])
                    expiry_str = row["expiration_date"].strip()
                    expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d").replace(tzinfo=UTC)

                    # Map instrument_type string to InstrumentType enum
                    instr_type_map: dict[str, InstrumentType] = {
                        "etf": InstrumentType.ETF,
                        "equity": InstrumentType.EQUITY,
                        "crude_futures": InstrumentType.CRUDE_FUTURES,
                        "options_chain": InstrumentType.OPTIONS_CHAIN,
                    }
                    instr_type = instr_type_map.get(instr_type_raw, InstrumentType.EQUITY)

                    prices.append(
                        RawPriceRecord(
                            instrument=instrument,
                            instrument_type=instr_type,
                            price=price_val,
                            timestamp=snapshot_time,
                            source="fixture",
                        )
                    )
                    options.append(
                        OptionRecord(
                            instrument=instrument,
                            strike=atm_strike_val,
                            expiration_date=expiry_dt,
                            implied_volatility=implied_vol_val,
                            option_type="call",
                            timestamp=snapshot_time,
                            source="fixture",
                        )
                    )
                except (KeyError, ValueError) as exc:
                    msg = f"fixture row malformed for instrument={instrument!r}: {exc}"
                    logger.warning("load_market_state_from_fixture: %s", msg)
                    errors.append(msg)
    except OSError as exc:
        logger.exception("load_market_state_from_fixture: cannot read %s", fixture_path)
        return MarketState(
            snapshot_time=snapshot_time,
            ingestion_errors=[str(exc)],
        )

    logger.info(
        "load_market_state_from_fixture: loaded %d price(s) and %d option(s) from %s",
        len(prices),
        len(options),
        fixture_path.name,
    )
    return MarketState(
        snapshot_time=snapshot_time,
        prices=prices,
        options=options,
        ingestion_errors=errors,
    )


# ---------------------------------------------------------------------------
# Feature set construction (replay — no DB, no live feature writes)
# ---------------------------------------------------------------------------


def _compute_sector_dispersion(market_state: MarketState) -> float | None:
    """
    Compute coefficient-of-variation dispersion across sector instruments.

    Args:
        market_state: MarketState containing price records.

    Returns:
        CV in [0.0, 1.0], or None if fewer than 2 sector instruments are present.
    """
    sector_prices = [
        p.price
        for p in market_state.prices
        if p.instrument in _SECTOR_INSTRUMENTS
    ]
    if len(sector_prices) < 2:
        return None
    mean = statistics.mean(sector_prices)
    if mean <= 0.0:
        return None
    std = statistics.pstdev(sector_prices)
    return min(std / mean, 1.0)


def _build_feature_set(market_state: MarketState) -> FeatureSet:
    """
    Derive a FeatureSet from a MarketState for backtesting replay.

    Volatility gaps are computed as (ATM implied vol) – (baseline realized vol).
    Baseline realized vols are long-term pre-crisis averages; this isolates the
    vol-spike signal present in each crisis event.

    Sector dispersion is computed as coefficient-of-variation across the sector
    instrument prices in the MarketState.

    Args:
        market_state: Populated MarketState from load_market_state_from_fixture.

    Returns:
        FeatureSet ready to pass into replay_pipeline.
    """
    # Aggregate ATM implied vol per instrument (average if multiple rows)
    iv_by_instrument: dict[str, list[float]] = {}
    for opt in market_state.options:
        if opt.implied_volatility is not None:
            iv_by_instrument.setdefault(opt.instrument, []).append(opt.implied_volatility)

    vol_gaps: list[VolatilityGap] = []
    for instrument, ivs in iv_by_instrument.items():
        avg_iv = sum(ivs) / len(ivs)
        baseline = _BASELINE_REALIZED_VOL.get(instrument, _DEFAULT_REALIZED_VOL)
        vol_gaps.append(
            VolatilityGap(
                instrument=instrument,
                realized_vol=baseline,
                implied_vol=avg_iv,
                gap=avg_iv - baseline,
                computed_at=market_state.snapshot_time,
            )
        )

    sector_dispersion = _compute_sector_dispersion(market_state)

    return FeatureSet(
        snapshot_time=market_state.snapshot_time,
        volatility_gaps=vol_gaps,
        sector_dispersion=sector_dispersion,
    )


# ---------------------------------------------------------------------------
# Replay pipeline (no DB writes to live tables)
# ---------------------------------------------------------------------------


def replay_pipeline(
    event_date: str,
    market_state: MarketState,
) -> list[StrategyCandidate]:
    """
    Run the strategy evaluation pipeline against an injected historical MarketState.

    Mirrors evaluate_strategies() but NEVER writes to the live strategy_candidates
    or feature_sets tables — results are returned to the caller only.

    Args:
        event_date:   Date string (YYYY-MM-DD) identifying the historical event.
            Used for logging and report naming.
        market_state: Historical market state (prices + options) for the event date.
            Build via load_market_state_from_fixture() or inject directly in tests.

    Returns:
        list[StrategyCandidate] sorted by edge_score descending.
        Empty list if no instrument meets _MIN_EDGE_SCORE — always returns, never raises.
    """
    logger.info("replay_pipeline: running for event_date=%s", event_date)

    feature_set = _build_feature_set(market_state)
    snapshot_time = market_state.snapshot_time
    candidates: list[StrategyCandidate] = []

    for instrument in INSTRUMENTS_IN_SCOPE:
        score = compute_edge_score(
            instrument,
            feature_set,
            supply_shock_probability=feature_set.supply_shock_probability,
            futures_curve_steepness=feature_set.futures_curve_steepness,
        )
        if score < _MIN_EDGE_SCORE:
            continue

        vg = next(
            (v for v in feature_set.volatility_gaps if v.instrument == instrument),
            None,
        )
        vol_gap_label = "positive" if (vg and vg.gap > 0) else "neutral"
        disp = feature_set.sector_dispersion or 0.0
        disp_label = "high" if disp > 0.15 else ("medium" if disp > 0.05 else "low")
        signals: dict[str, str] = {
            "volatility_gap": vol_gap_label,
            "sector_dispersion": disp_label,
        }

        for structure in _REPLAY_STRUCTURES:
            candidates.append(
                StrategyCandidate(
                    instrument=instrument,
                    structure=structure,
                    expiration=_DEFAULT_EXPIRATION_DAYS,
                    edge_score=score,
                    signals=signals,
                    generated_at=snapshot_time,
                )
            )

    candidates.sort(key=lambda c: c.edge_score, reverse=True)
    logger.info(
        "replay_pipeline: event_date=%s → %d candidate(s) generated",
        event_date,
        len(candidates),
    )
    return candidates


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


def write_backtest_report(
    event_date: str,
    event_name: str,
    candidates: list[StrategyCandidate],
    report_dir: Path = REPORTS_DIR,
) -> Path:
    """
    Write a markdown backtest report for a single event replay.

    Args:
        event_date:  YYYY-MM-DD string identifying the event.
        event_name:  Human-readable event name for the report header.
        candidates:  StrategyCandidate list from replay_pipeline().
        report_dir:  Directory to write the report into.
            Created automatically if it does not exist.

    Returns:
        Path to the written report file.
    """
    report_dir.mkdir(parents=True, exist_ok=True)
    slug = event_date
    report_path = report_dir / f"{slug}.md"

    top_candidates = [
        c
        for c in candidates
        if c.structure in (OptionStructure.LONG_STRADDLE, OptionStructure.CALL_SPREAD)
    ][:5]

    high_edge = [c for c in candidates if c.edge_score >= _EDGE_SCORE_ASSERTION_THRESHOLD]
    assertion_passed = len(high_edge) > 0

    lines: list[str] = [
        f"# Backtest Report — {event_name}",
        "",
        f"**Event date:** {event_date}  ",
        f"**Candidates generated:** {len(candidates)}  ",
        f"**Edge > {_EDGE_SCORE_ASSERTION_THRESHOLD:.0%} assertion:** "
        f"{'PASS ✓' if assertion_passed else 'FAIL ✗'}  ",
        "",
        "## Top Candidates (long_straddle / call_spread)",
        "",
        "| Instrument | Structure | Edge Score | Signals |",
        "|------------|-----------|-----------|---------|",
    ]

    for c in top_candidates:
        sig_summary = ", ".join(f"{k}={v}" for k, v in c.signals.items())
        lines.append(
            f"| {c.instrument} | {c.structure.value} "
            f"| {c.edge_score:.4f} | {sig_summary} |"
        )

    if not top_candidates:
        lines.append("| — | — | — | no candidates met threshold |")

    lines += [
        "",
        "## Commentary",
        "",
        f"Replay ran against the `backtests/fixtures/{slug}.csv` fixture. "
        f"Implied volatility values reflect ATM options on the event date. "
        f"Realized volatility baselines are long-term pre-crisis averages "
        f"(`_BASELINE_REALIZED_VOL`). Sector dispersion is computed as "
        f"coefficient-of-variation across XOM, CVX, USO, XLE prices from the fixture.",
        "",
        "---",
        f"_Generated by `scripts/backtest_harness.py` · Issue #166_",
    ]

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("write_backtest_report: wrote %s", report_path)
    return report_path


# ---------------------------------------------------------------------------
# Validation runner
# ---------------------------------------------------------------------------


def run_event_validations(
    fixtures_dir: Path = FIXTURES_DIR,
    report_dir: Path = REPORTS_DIR,
) -> dict[str, bool]:
    """
    Run replay_pipeline against all three known volatility events and assert
    that each produces at least one long_straddle or call_spread candidate
    with edge_score > _EDGE_SCORE_ASSERTION_THRESHOLD.

    Args:
        fixtures_dir: Directory containing fixture CSV files.
        report_dir:   Directory to write markdown reports into.

    Returns:
        Dict mapping event stem → assertion_passed (True/False).
    """
    results: dict[str, bool] = {}

    for fixture_stem, event_name in KNOWN_EVENTS:
        event_date = fixture_stem[:10]  # first 10 chars = YYYY-MM-DD
        fixture_path = fixtures_dir / f"{fixture_stem}.csv"

        market_state = load_market_state_from_fixture(fixture_path, event_date)
        candidates = replay_pipeline(event_date, market_state)

        high_edge = [
            c
            for c in candidates
            if c.edge_score >= _EDGE_SCORE_ASSERTION_THRESHOLD
            and c.structure in (OptionStructure.LONG_STRADDLE, OptionStructure.CALL_SPREAD)
        ]
        assertion_passed = len(high_edge) > 0

        write_backtest_report(event_date, event_name, candidates, report_dir)

        if assertion_passed:
            logger.info(
                "run_event_validations: %s PASS — %d high-edge candidate(s)",
                event_date,
                len(high_edge),
            )
        else:
            logger.warning(
                "run_event_validations: %s FAIL — no candidate with edge_score > %.2f",
                event_date,
                _EDGE_SCORE_ASSERTION_THRESHOLD,
            )

        results[fixture_stem] = assertion_passed

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Run all event validations and print a summary."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    results = run_event_validations()
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\nBacktest validation: {passed}/{total} events passed edge assertion.\n")
    for stem, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {stem}")
    print()
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
