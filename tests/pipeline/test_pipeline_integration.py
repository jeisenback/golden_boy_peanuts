"""
Full pipeline integration test — Phase 1 acceptance gate.

Validates the complete data flow:
    seeded market data
    → Feature Generation reads prices + options, computes FeatureSet, persists to DB
    → Strategy Evaluation produces ranked StrategyCandidate rows, persists to DB

The Ingestion Agent's live API fetches are NOT exercised here (they require
real API keys). Instead, seed data is inserted directly via the test's DB
connection, which is the intended isolation strategy per issue #20.

Golden dataset:
    USO — 30 daily prices, alternating ±daily_vol log returns
          daily_vol = 0.15 / sqrt(252) ≈ 0.009449
          realized vol ≈ 15.26%  |  ATM IV = 22%  |  gap ≈ +6.74%
    XLE — 30 daily prices, daily_vol = 0.13 / sqrt(252) ≈ 0.008191
          realized vol ≈ 13.22%  |  ATM IV = 18%  |  gap ≈ +4.78%
    WTI (CL=F) — spot price only, no options (Phase 1 scope)
    XOM, CVX — single spot prices for sector dispersion computation

All tests are marked @pytest.mark.integration and excluded from the default
`pytest -m "not integration"` run.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
import math
import os
import pathlib
import subprocess
import sys
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.agents.feature_generation.feature_generation_agent import run_feature_generation
from src.agents.ingestion.models import InstrumentType, MarketState, OptionRecord, RawPriceRecord
from src.agents.strategy_evaluation.strategy_evaluation_agent import evaluate_strategies

# Disable testcontainers Reaper (Ryuk) on Windows where port mapping is unavailable.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------
_PATCH_FG_ENGINE = "src.agents.feature_generation.feature_generation_agent.get_engine"
_PATCH_SE_ENGINE = "src.agents.strategy_evaluation.strategy_evaluation_agent.get_engine"

# ---------------------------------------------------------------------------
# Schema paths and supplemental DDL
# ---------------------------------------------------------------------------
_SCHEMA_PATH = pathlib.Path(__file__).parents[2] / "db" / "schema.sql"

# feature_sets is defined in db/schema.sql alongside the other pipeline tables.

# ---------------------------------------------------------------------------
# Postgres container image
# ---------------------------------------------------------------------------
_PG_IMAGE: str = "postgres:15"

# ---------------------------------------------------------------------------
# Golden dataset constants
#
# USO: 30 alternating ±daily_vol log-return prices, daily_vol = 0.15/sqrt(252)
#      realized vol ≈ 15.26%  |  ATM IV = 22%  |  expected gap ≈ +6.74%
# XLE: 30 alternating ±daily_vol log-return prices, daily_vol = 0.13/sqrt(252)
#      realized vol ≈ 13.22%  |  ATM IV = 18%  |  expected gap ≈ +4.78%
# ---------------------------------------------------------------------------
_PRICE_SERIES_LENGTH: int = 30  # trading-day lookback for realized-vol computation

_USO_START_PRICE: float = 50.0
_USO_ATM_IV: float = 0.22
_USO_DAILY_VOL: float = 0.15 / math.sqrt(252)

_XLE_START_PRICE: float = 80.0
_XLE_ATM_IV: float = 0.18
_XLE_DAILY_VOL: float = 0.13 / math.sqrt(252)

_WTI_PRICE: float = 75.0
_XOM_PRICE: float = 110.0
_CVX_PRICE: float = 155.0

_OPTION_EXPIRY = datetime(2026, 6, 20, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Seed data constants — representative but not domain-meaningful
# ---------------------------------------------------------------------------
_SEED_PRICE_VOLUME: int = 1_000_000  # generic daily volume for seeded price rows
_SEED_OPTION_OI: int = 1_000  # open interest for seeded ATM option rows
_SEED_OPTION_VOLUME: int = 500  # volume for seeded ATM option rows
_PRICE_ROW_SPACING_MINUTES: int = 1  # minute gap between consecutive seed price rows

# ---------------------------------------------------------------------------
# Acceptance thresholds
# ---------------------------------------------------------------------------
_USO_EDGE_SCORE_MIN: float = 0.30  # AC: edge_score > 0.30
_MIN_CANDIDATE_ROWS: int = 2  # AC: at least 2 StrategyCandidate rows
# PRD Section 9 fields: instrument, structure, expiration, edge_score, signals, generated_at
_PRD_FIELD_COUNT: int = 6


def _build_prices(
    start: float,
    daily_vol: float,
    n: int = _PRICE_SERIES_LENGTH,
) -> list[float]:
    """Build a deterministic price series of length n using alternating log returns.

    Each step alternates between +daily_vol and -daily_vol, producing a
    series with a known realized volatility ≈ daily_vol * sqrt(252).

    Args:
        start: Starting price (e.g. 50.0 for USO).
        daily_vol: Daily log-return magnitude (annualized_vol / sqrt(252)).
        n: Number of price points to generate; defaults to _PRICE_SERIES_LENGTH.

    Returns:
        List of n float prices in chronological order.
    """
    prices = [start]
    for i in range(n - 1):
        ret = daily_vol if i % 2 == 0 else -daily_vol
        prices.append(prices[-1] * math.exp(ret))
    return prices


_USO_PRICES: list[float] = _build_prices(_USO_START_PRICE, _USO_DAILY_VOL)
_XLE_PRICES: list[float] = _build_prices(_XLE_START_PRICE, _XLE_DAILY_VOL)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine() -> Generator[Engine, None, None]:
    """Start a real Postgres container, apply schema, yield engine."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer(_PG_IMAGE) as pg:
        engine = create_engine(pg.get_connection_url())
        with engine.begin() as conn:
            conn.exec_driver_sql(_SCHEMA_PATH.read_text(encoding="utf-8"))
        yield engine


@pytest.fixture(autouse=True)
def _clean_tables(pg_engine: Engine) -> Generator[None, None, None]:
    """Truncate all pipeline tables before each test for isolation.

    Resets market_prices, options_chain, feature_sets, and strategy_candidates
    so that each test starts from a known-empty state regardless of insertion
    order or prior test failures.
    """
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE market_prices, options_chain, feature_sets,"
                " strategy_candidates RESTART IDENTITY"
            )
        )
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_prices(
    engine: Engine,
    instrument: str,
    instrument_type: str,
    prices: list[float],
    base_time: datetime | None = None,
) -> None:
    """Insert price rows into market_prices with deterministic timestamps.

    Rows are spaced _PRICE_ROW_SPACING_MINUTES apart starting from base_time
    so that ORDER BY timestamp produces a stable chronological sequence.

    Args:
        engine: SQLAlchemy Engine connected to the test database.
        instrument: Ticker symbol, e.g. 'USO'.
        instrument_type: Raw instrument type string, e.g. 'etf'.
        prices: Sequence of price floats to insert (oldest first).
        base_time: UTC datetime for the first row; defaults to 2026-01-01 00:00 UTC.
    """
    if base_time is None:
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
    sql = text(
        """
        INSERT INTO market_prices
            (instrument, instrument_type, price, volume, source, timestamp)
        VALUES
            (:instrument, :instrument_type, :price, :volume, :source, :timestamp)
    """
    )
    rows = [
        {
            "instrument": instrument,
            "instrument_type": instrument_type,
            "price": p,
            "volume": _SEED_PRICE_VOLUME,
            "source": "test",
            "timestamp": base_time + timedelta(minutes=i * _PRICE_ROW_SPACING_MINUTES),
        }
        for i, p in enumerate(prices)
    ]
    with engine.begin() as conn:
        conn.execute(sql, rows)


def _seed_option(
    engine: Engine,
    instrument: str,
    strike: float,
    atm_iv: float,
) -> None:
    """Insert a single ATM call option row into options_chain.

    Uses _OPTION_EXPIRY, _SEED_OPTION_OI, and _SEED_OPTION_VOLUME constants
    so that all seeded options share the same expiry and representative liquidity.

    Args:
        engine: SQLAlchemy Engine connected to the test database.
        instrument: Underlying ticker symbol, e.g. 'USO'.
        strike: ATM strike price (should equal the current spot price).
        atm_iv: Implied volatility for the ATM option (e.g. 0.22 for 22%).
    """
    sql = text(
        """
        INSERT INTO options_chain
            (instrument, strike, expiration_date, implied_volatility,
             open_interest, volume, option_type, source, timestamp)
        VALUES
            (:instrument, :strike, :expiration_date, :implied_volatility,
             :open_interest, :volume, :option_type, :source, :timestamp)
    """
    )
    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "instrument": instrument,
                "strike": strike,
                "expiration_date": _OPTION_EXPIRY,
                "implied_volatility": atm_iv,
                "open_interest": _SEED_OPTION_OI,
                "volume": _SEED_OPTION_VOLUME,
                "option_type": "call",
                "source": "test",
                "timestamp": datetime.now(tz=UTC),
            },
        )


def _build_market_state() -> MarketState:
    """Build a MarketState from the golden dataset prices and options.

    Includes USO and XLE with ATM call options for volatility gap computation,
    WTI spot-only (no Phase 1 options), and XOM + CVX for sector dispersion.

    Returns:
        MarketState with snapshot_time=now(UTC), 5 price records, 2 option records.
    """
    now = datetime.now(tz=UTC)
    prices = [
        RawPriceRecord(
            instrument="USO",
            instrument_type=InstrumentType.ETF,
            price=_USO_PRICES[-1],
            volume=5_000_000,
            timestamp=now,
            source="test",
        ),
        RawPriceRecord(
            instrument="XLE",
            instrument_type=InstrumentType.ETF,
            price=_XLE_PRICES[-1],
            volume=3_000_000,
            timestamp=now,
            source="test",
        ),
        RawPriceRecord(
            instrument="CL=F",
            instrument_type=InstrumentType.CRUDE_FUTURES,
            price=_WTI_PRICE,
            volume=50_000,
            timestamp=now,
            source="test",
        ),
        RawPriceRecord(
            instrument="XOM",
            instrument_type=InstrumentType.EQUITY,
            price=_XOM_PRICE,
            volume=8_000_000,
            timestamp=now,
            source="test",
        ),
        RawPriceRecord(
            instrument="CVX",
            instrument_type=InstrumentType.EQUITY,
            price=_CVX_PRICE,
            volume=4_000_000,
            timestamp=now,
            source="test",
        ),
    ]
    options = [
        OptionRecord(
            instrument="USO",
            strike=_USO_PRICES[-1],
            expiration_date=_OPTION_EXPIRY,
            implied_volatility=_USO_ATM_IV,
            open_interest=_SEED_OPTION_OI,
            volume=_SEED_OPTION_VOLUME,
            option_type="call",
            timestamp=now,
            source="test",
        ),
        OptionRecord(
            instrument="XLE",
            strike=_XLE_PRICES[-1],
            expiration_date=_OPTION_EXPIRY,
            implied_volatility=_XLE_ATM_IV,
            open_interest=_SEED_OPTION_OI,
            volume=_SEED_OPTION_VOLUME,
            option_type="call",
            timestamp=now,
            source="test",
        ),
    ]
    return MarketState(snapshot_time=now, prices=prices, options=options)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_full_pipeline_feature_set_written_to_db(pg_engine: Engine) -> None:
    """
    Phase 1 pipeline AC: run_feature_generation() persists a FeatureSet row.

    Seeds USO and XLE price history + ATM options. Patches get_engine in both
    agents to use the test container engine. Asserts the feature_sets table
    has exactly one row with non-None volatility_gaps and sector_dispersion.
    """
    _seed_prices(pg_engine, "USO", "etf", _USO_PRICES)
    _seed_prices(pg_engine, "XLE", "etf", _XLE_PRICES)

    market_state = _build_market_state()

    with (
        patch(_PATCH_FG_ENGINE, return_value=pg_engine),
        patch(_PATCH_SE_ENGINE, return_value=pg_engine),
    ):
        feature_set = run_feature_generation(market_state, events=[])

    # FeatureSet in-memory assertions
    assert (
        feature_set.feature_errors == []
    ), f"unexpected feature_errors: {feature_set.feature_errors}"
    uso_gap = next((g for g in feature_set.volatility_gaps if g.instrument == "USO"), None)
    assert uso_gap is not None, "USO volatility gap not computed"
    assert uso_gap.gap > 0, "Expected positive USO volatility gap (IV > realized)"

    # DB persistence assertion
    with pg_engine.connect() as conn:
        row = conn.execute(
            text("SELECT snapshot_time, volatility_gaps, sector_dispersion FROM feature_sets")
        ).fetchone()
    assert row is not None, "feature_sets table is empty after run_feature_generation()"
    assert row[1] is not None, "volatility_gaps not persisted"
    assert row[2] is not None, "sector_dispersion not persisted"


@pytest.mark.integration
def test_full_pipeline_strategy_candidates_written_to_db(pg_engine: Engine) -> None:
    """
    Phase 1 pipeline AC: evaluate_strategies() produces ≥ 2 StrategyCandidate rows.

    Runs the full two-step pipeline (feature generation → strategy evaluation).
    Asserts the strategy_candidates table has at least 2 rows with complete
    PRD Section 9 schema.
    """
    _seed_prices(pg_engine, "USO", "etf", _USO_PRICES)
    _seed_prices(pg_engine, "XLE", "etf", _XLE_PRICES)

    market_state = _build_market_state()

    with (
        patch(_PATCH_FG_ENGINE, return_value=pg_engine),
        patch(_PATCH_SE_ENGINE, return_value=pg_engine),
    ):
        feature_set = run_feature_generation(market_state, events=[])
        candidates = evaluate_strategies(feature_set)

    assert (
        len(candidates) >= _MIN_CANDIDATE_ROWS
    ), f"expected >= {_MIN_CANDIDATE_ROWS} candidates, got {len(candidates)}"

    # Verify DB rows
    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT instrument, structure, expiration, edge_score, signals, generated_at"
                " FROM strategy_candidates ORDER BY edge_score DESC"
            )
        ).fetchall()

    assert (
        len(rows) >= _MIN_CANDIDATE_ROWS
    ), f"expected >= {_MIN_CANDIDATE_ROWS} DB rows, got {len(rows)}"

    # Assert complete PRD Section 9 schema on every row
    for row in rows:
        instr, struct, expiration, edge_score, signals, gen_at = row
        assert instr is not None, "instrument is NULL"
        assert struct is not None, "structure is NULL"
        assert expiration is not None, "expiration is NULL"
        assert edge_score is not None, "edge_score is NULL"
        assert signals is not None, "signals is NULL"
        assert gen_at is not None, "generated_at is NULL"
        assert 0.0 <= float(edge_score) <= 1.0, f"edge_score {edge_score} out of [0, 1]"


@pytest.mark.integration
def test_full_pipeline_uso_long_straddle_edge_score(pg_engine: Engine) -> None:
    """
    Golden dataset AC: USO long_straddle candidate has edge_score > 0.30.

    Uses the golden dataset (USO realized vol ≈ 15%, ATM IV = 22%, gap ≈ +6.74%)
    and asserts the USO long_straddle candidate meets the Phase 1 acceptance threshold.
    """
    _seed_prices(pg_engine, "USO", "etf", _USO_PRICES)
    _seed_prices(pg_engine, "XLE", "etf", _XLE_PRICES)

    market_state = _build_market_state()

    with (
        patch(_PATCH_FG_ENGINE, return_value=pg_engine),
        patch(_PATCH_SE_ENGINE, return_value=pg_engine),
    ):
        feature_set = run_feature_generation(market_state, events=[])
        candidates = evaluate_strategies(feature_set)

    uso_straddle = next(
        (c for c in candidates if c.instrument == "USO" and c.structure.value == "long_straddle"),
        None,
    )
    assert uso_straddle is not None, "No USO long_straddle candidate produced"
    assert uso_straddle.edge_score > _USO_EDGE_SCORE_MIN, (
        f"USO long_straddle edge_score {uso_straddle.edge_score:.4f}"
        f" is not > {_USO_EDGE_SCORE_MIN}"
    )


@pytest.mark.integration
def test_full_pipeline_no_runtime_import_violations() -> None:
    """
    ESOD AC: no langchain.* or langgraph.* imports in src/.

    Runs the check_runtime_imports.py scanner in-process via subprocess so
    that the assertion is meaningful (not just trusting local ruff/mypy).
    """
    script = pathlib.Path(__file__).parents[2] / ".github" / "scripts" / "check_runtime_imports.py"
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(pathlib.Path(__file__).parents[2]),
    )
    assert result.returncode == 0, f"Runtime import check FAILED:\n{result.stdout}\n{result.stderr}"
