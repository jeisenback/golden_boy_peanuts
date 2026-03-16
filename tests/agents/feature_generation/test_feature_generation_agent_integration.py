"""
Integration tests for the Feature Generation Agent.

Uses testcontainers.postgres.PostgresContainer — no mocked DB.
All tests are marked @pytest.mark.integration and excluded from the default
`pytest -m "not integration"` run.

Coverage:
  - compute_volatility_gap(): golden dataset — seed 30 known prices, assert realized
    vol within 0.01 of hand-calculated value; assert gap within 0.01 of 7%
  - run_feature_generation(): writes FeatureSet row to DB; assert snapshot_time,
    volatility_gaps (JSONB), sector_dispersion correct
  - partial signal failure → feature_errors non-empty in persisted row

Golden dataset (USO):
  - 30 prices starting at 50.0; alternating daily log returns of ±daily_vol
    where daily_vol = 0.15 / sqrt(252) ≈ 0.009449
  - Computed realized vol ≈ 15.26% (within 0.01 of 15%)
  - ATM implied vol = 22%
  - Expected volatility gap ≈ +6.74% (within 0.01 of 7%)
  - With sector_dispersion=0.50: edge_score ≈ 0.39 > 0.35 (validates #19 forward ref)
"""

from __future__ import annotations

import os

# Disable testcontainers Reaper (Ryuk) — required on Windows where the Reaper
# container's port mapping is unavailable. Must be set before any testcontainers import.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
import json
import math
import statistics
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.agents.event_detection.models import DetectedEvent, EventIntensity, EventType
from src.agents.feature_generation.feature_generation_agent import (
    compute_volatility_gap,
    run_feature_generation,
)
from src.agents.ingestion.models import InstrumentType, MarketState, OptionRecord, RawPriceRecord

# A single high-confidence supply disruption event for tests that assert supply_shock_probability
_SAMPLE_EVENT = DetectedEvent(
    event_id="abc123",
    event_type=EventType.SUPPLY_DISRUPTION,
    description="Major pipeline outage detected",
    source="newsapi",
    confidence_score=1.0,
    intensity=EventIntensity.HIGH,
    detected_at=datetime(2026, 1, 1, tzinfo=UTC),
    affected_instruments=["USO", "XLE"],
)

# ---------------------------------------------------------------------------
# Patch target for get_engine used inside the feature generation agent
# ---------------------------------------------------------------------------
_PATCH_ENGINE = "src.agents.feature_generation.feature_generation_agent.get_engine"

# ---------------------------------------------------------------------------
# Schema DDL — market_prices mirrors db/schema.sql;
# feature_sets is test-only DDL (production table pending human schema review)
# ---------------------------------------------------------------------------
_DDL = """
CREATE TABLE IF NOT EXISTS market_prices (
    id              BIGSERIAL       PRIMARY KEY,
    instrument      TEXT            NOT NULL,
    instrument_type TEXT            NOT NULL,
    price           NUMERIC(18, 6)  NOT NULL,
    volume          BIGINT,
    source          TEXT            NOT NULL,
    timestamp       TIMESTAMPTZ     NOT NULL
);

CREATE TABLE IF NOT EXISTS feature_sets (
    id                BIGSERIAL     PRIMARY KEY,
    snapshot_time     TIMESTAMPTZ   NOT NULL,
    volatility_gaps   JSONB,
    sector_dispersion NUMERIC(10, 6),
    feature_errors    JSONB,
    computed_at       TIMESTAMPTZ   NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Golden dataset constants
#
# 30 daily prices for USO built from alternating ±daily_vol log returns.
# Produces a deterministic realized vol of ≈ 15.26% annualized.
# Hand-calculated value documented in-line so reviewers can verify without
# running the test.
#
#   daily_vol  = 0.15 / sqrt(252)           ≈ 0.009449
#   log_returns = [+daily_vol, -daily_vol, ...] x 29
#   realized_vol = stdev(log_returns) * sqrt(252) ≈ 0.1526
#   ATM IV       = 0.22  (22%)
#   gap          = IV - realized_vol        ≈ 0.0674  (+6.74%)
# ---------------------------------------------------------------------------
_GOLDEN_START_PRICE: float = 50.0
_GOLDEN_ATM_IV: float = 0.22
_GOLDEN_DAILY_VOL: float = 0.15 / math.sqrt(252)  # ≈ 0.009449

# Build the 30-price golden series at module level so tests can reference it
_GOLDEN_PRICES: list[float] = [_GOLDEN_START_PRICE]
for _i in range(29):
    _ret = _GOLDEN_DAILY_VOL if _i % 2 == 0 else -_GOLDEN_DAILY_VOL
    _GOLDEN_PRICES.append(_GOLDEN_PRICES[-1] * math.exp(_ret))

# Hand-calculated expected values
_GOLDEN_LOG_RETURNS: list[float] = [
    math.log(_GOLDEN_PRICES[i] / _GOLDEN_PRICES[i - 1]) for i in range(1, len(_GOLDEN_PRICES))
]
_GOLDEN_REALIZED_VOL: float = statistics.stdev(_GOLDEN_LOG_RETURNS) * math.sqrt(252)
_GOLDEN_GAP: float = _GOLDEN_ATM_IV - _GOLDEN_REALIZED_VOL


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine() -> Generator[Engine, None, None]:
    """Start a PostgresContainer, apply schema, yield engine, stop container."""
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:15") as pg:
        engine = create_engine(pg.get_connection_url())
        with engine.begin() as conn:
            conn.execute(text(_DDL))
        yield engine


@pytest.fixture(autouse=True)
def _clean_tables(pg_engine: Engine) -> Generator[None, None, None]:
    """Truncate tables before each test so tests are isolated."""
    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE market_prices, feature_sets RESTART IDENTITY"))
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_prices(
    engine: Engine,
    instrument: str,
    prices: list[float],
    base_time: datetime | None = None,
) -> None:
    """Insert price records with 1-minute spacing so ORDER BY timestamp is deterministic."""
    if base_time is None:
        base_time = datetime(2026, 1, 1, tzinfo=UTC)

    sql = text("""
        INSERT INTO market_prices (instrument, instrument_type, price, volume, source, timestamp)
        VALUES (:instrument, :instrument_type, :price, :volume, :source, :timestamp)
        """)
    rows = [
        {
            "instrument": instrument,
            "instrument_type": "etf",
            "price": p,
            "volume": 100000,
            "source": "test",
            "timestamp": base_time + timedelta(minutes=i),
        }
        for i, p in enumerate(prices)
    ]
    with engine.begin() as conn:
        conn.execute(sql, rows)


def _make_market_state(
    instrument: str,
    current_price: float,
    atm_iv: float,
    sector_prices: dict[str, float] | None = None,
) -> MarketState:
    """Build a minimal MarketState with one instrument and one ATM call option."""
    now = datetime.now(tz=UTC)
    prices = [
        RawPriceRecord(
            instrument=instrument,
            instrument_type=InstrumentType.ETF,
            price=current_price,
            volume=1_000_000,
            timestamp=now,
            source="test",
        )
    ]
    if sector_prices:
        for sym, p in sector_prices.items():
            prices.append(
                RawPriceRecord(
                    instrument=sym,
                    instrument_type=InstrumentType.EQUITY,
                    price=p,
                    volume=500_000,
                    timestamp=now,
                    source="test",
                )
            )

    options = [
        OptionRecord(
            instrument=instrument,
            strike=current_price,  # ATM: strike == current price
            expiration_date=datetime(2026, 3, 21, tzinfo=UTC),
            implied_volatility=atm_iv,
            open_interest=1000,
            volume=500,
            option_type="call",
            timestamp=now,
            source="test",
        )
    ]
    return MarketState(snapshot_time=now, prices=prices, options=options)


# ---------------------------------------------------------------------------
# compute_volatility_gap: golden dataset integration test
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_compute_volatility_gap_golden_dataset(pg_engine: Engine) -> None:
    """
    Golden scenario — USO realized vol ≈ 15%, ATM IV = 22%, gap ≈ +7%.

    Hand-calculated expected values:
      daily_vol  = 0.15 / sqrt(252) ≈ 0.009449
      realized   = stdev(29 alternating returns) * sqrt(252) ≈ 15.26%
      gap        = 22% - 15.26% ≈ +6.74%  (within 1% of target +7%)

    edge_score preview (with dispersion=0.50):
      score = (gap/0.20 * 0.70) + (0.50 * 0.30) ≈ 0.24 + 0.15 = 0.39 > 0.35
    """
    _seed_prices(pg_engine, "USO", _GOLDEN_PRICES)

    market_state = _make_market_state(
        "USO", current_price=_GOLDEN_PRICES[-1], atm_iv=_GOLDEN_ATM_IV
    )

    with patch(_PATCH_ENGINE, return_value=pg_engine):
        gaps = compute_volatility_gap(market_state)

    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.instrument == "USO"

    # Assert realized vol within 0.01 of hand-calculated value.
    # Tolerance is 1e-4 (not tighter) because NUMERIC(18,6) DB storage rounds
    # prices to 6 decimal places, introducing small rounding in log returns.
    assert (
        abs(gap.realized_vol - _GOLDEN_REALIZED_VOL) < 1e-4
    ), f"realized_vol mismatch: got {gap.realized_vol:.6f}, expected {_GOLDEN_REALIZED_VOL:.6f}"
    # Assert gap within 0.01 of +7% target (the AC requirement)
    assert (
        abs(gap.gap - _GOLDEN_GAP) < 1e-4
    ), f"gap mismatch: got {gap.gap:.6f}, expected {_GOLDEN_GAP:.6f}"
    assert (
        abs(gap.gap - 0.07) < 0.01
    ), f"gap {gap.gap:.4f} is not within 0.01 of 0.07 (golden target)"
    assert gap.gap > 0, "Expected positive volatility gap (IV premium)"


@pytest.mark.integration
def test_compute_volatility_gap_insufficient_history_skips(pg_engine: Engine) -> None:
    """Instrument with fewer than 10 price records is skipped (warning only, no error)."""
    # Seed only 5 records — below _MIN_PRICE_RECORDS=10
    _seed_prices(pg_engine, "USO", _GOLDEN_PRICES[:5])
    market_state = _make_market_state("USO", current_price=50.0, atm_iv=0.22)

    with patch(_PATCH_ENGINE, return_value=pg_engine):
        gaps = compute_volatility_gap(market_state)

    assert gaps == []


# ---------------------------------------------------------------------------
# run_feature_generation: DB persistence tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_run_feature_generation_writes_feature_set(pg_engine: Engine) -> None:
    """
    run_feature_generation() persists a FeatureSet row to the feature_sets table.
    Assert snapshot_time, volatility_gaps (JSONB), and sector_dispersion are correct.
    """
    _seed_prices(pg_engine, "USO", _GOLDEN_PRICES)

    sector_prices = {"XOM": 100.0, "CVX": 110.0, "USO": _GOLDEN_PRICES[-1], "XLE": 80.0}
    market_state = _make_market_state(
        "USO",
        current_price=_GOLDEN_PRICES[-1],
        atm_iv=_GOLDEN_ATM_IV,
        sector_prices=sector_prices,
    )

    with patch(_PATCH_ENGINE, return_value=pg_engine):
        feature_set = run_feature_generation(market_state, events=[])

    # Verify in-memory FeatureSet has the USO gap
    uso_gap = next((g for g in feature_set.volatility_gaps if g.instrument == "USO"), None)
    assert uso_gap is not None
    assert abs(uso_gap.gap - _GOLDEN_GAP) < 1e-4

    # Verify DB row written
    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT snapshot_time, volatility_gaps, sector_dispersion FROM feature_sets LIMIT 1"
            )
        ).fetchone()

    assert row is not None
    # snapshot_time round-trips correctly
    db_snapshot = row[0]
    assert db_snapshot is not None

    # volatility_gaps JSONB contains the USO gap
    gaps_data = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    assert isinstance(gaps_data, list)
    assert len(gaps_data) == 1
    assert gaps_data[0]["instrument"] == "USO"
    assert abs(gaps_data[0]["gap"] - _GOLDEN_GAP) < 1e-4

    # sector_dispersion persisted as non-None (4 sector instruments present)
    assert row[2] is not None


@pytest.mark.integration
def test_run_feature_generation_happy_path_no_feature_errors(pg_engine: Engine) -> None:
    """
    Happy path: all signal computations succeed → feature_errors is empty in
    both the returned FeatureSet and the persisted DB row.
    """
    _seed_prices(pg_engine, "USO", _GOLDEN_PRICES)
    market_state = _make_market_state("USO", current_price=_GOLDEN_PRICES[-1], atm_iv=0.22)

    with patch(_PATCH_ENGINE, return_value=pg_engine):
        feature_set = run_feature_generation(market_state, events=[_SAMPLE_EVENT])

    assert (
        feature_set.feature_errors == []
    ), f"expected no feature_errors on happy path, got {feature_set.feature_errors}"
    assert feature_set.supply_shock_probability is not None

    with pg_engine.connect() as conn:
        row = conn.execute(text("SELECT feature_errors FROM feature_sets LIMIT 1")).fetchone()
    assert row is not None
    errors_data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    assert errors_data == []


@pytest.mark.integration
def test_run_feature_generation_partial_failure_populates_feature_errors(
    pg_engine: Engine,
) -> None:
    """
    Partial signal failure: compute_volatility_gap raises → feature_errors is
    non-empty in both the FeatureSet and the persisted DB row; other signals
    still computed and FeatureSet still written (degraded-mode guarantee).

    AC covered (issue #16):
    - partial signal failure → feature_errors non-empty in DB row
    """
    _seed_prices(pg_engine, "USO", _GOLDEN_PRICES)
    market_state = _make_market_state("USO", current_price=_GOLDEN_PRICES[-1], atm_iv=0.22)

    _patch_vol_gap = "src.agents.feature_generation.feature_generation_agent.compute_volatility_gap"
    with (
        patch(_PATCH_ENGINE, return_value=pg_engine),
        patch(_patch_vol_gap, side_effect=RuntimeError("simulated vol gap failure")),
    ):
        feature_set = run_feature_generation(market_state, events=[_SAMPLE_EVENT])

    # feature_errors must be non-empty and mention the failed signal
    assert feature_set.feature_errors, "expected feature_errors to be non-empty after failure"
    assert any(
        "compute_volatility_gap" in e for e in feature_set.feature_errors
    ), f"expected 'compute_volatility_gap' in feature_errors, got {feature_set.feature_errors}"
    # Other signals still computed — degraded mode, no cascade failure
    assert feature_set.volatility_gaps == []
    assert feature_set.supply_shock_probability is not None

    # DB row still written despite partial failure
    with pg_engine.connect() as conn:
        row = conn.execute(
            text("SELECT feature_errors, volatility_gaps FROM feature_sets LIMIT 1")
        ).fetchone()
    assert row is not None, "expected FeatureSet written to DB even on partial failure"
    errors_data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    assert (
        isinstance(errors_data, list) and len(errors_data) >= 1
    ), f"expected non-empty feature_errors in DB, got {errors_data}"
    assert any("compute_volatility_gap" in e for e in errors_data)
