-- =============================================================================
-- db/migrations/add_backtest_tables.sql
-- Issue #172 — Sprint 9 Phase 3 Backtesting Core
-- =============================================================================
--
-- Creates two tables that isolate backtest data from the live production tables:
--
--   backtest_candidates  — historical candidates generated during pipeline replay
--   backtest_outcomes    — actual underlying close at expiration + P&L verdict
--
-- Isolation rationale:
--   run_backtest_pipeline() calls compute_* functions directly (not
--   run_feature_generation) to avoid writing to live feature_sets.
--   backtest_candidates is likewise isolated from strategy_candidates so that
--   historical replay rows never appear in production reporting queries.
--
-- profitable=NULL (not a skipped row) when yfinance returns no data — the row
-- is still inserted for audit purposes with profitable left NULL.
--
-- entry_premium, upper_strike, lower_strike are nullable:
--   - NULL for long_straddle (only underlying_close is needed for P&L)
--   - populated for call_spread / put_spread
--   - calendar_spread deferred (post-Sprint-A issue)
--
-- HUMAN SIGN-OFF REQUIRED before running against any live DB.
-- Apply: psql $DATABASE_URL -f db/migrations/add_backtest_tables.sql
-- Verify: \d backtest_candidates   \d backtest_outcomes
-- =============================================================================

-- Enable pgcrypto for gen_random_uuid() if not already enabled.
-- NOTE: On RDS / managed Postgres, this extension may already be present.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- -----------------------------------------------------------------------------
-- backtest_candidates
--
-- One row per strategy candidate produced during a backtest replay slice.
-- snapshot_time is the point-in-time of the historical market data slice used
-- to generate this candidate (not the wall-clock time the row was written).
--
-- Structure values must match the live strategy_candidates CHECK constraint.
-- TIMESTAMPTZ ensures TimescaleDB hypertable conversion requires zero changes.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backtest_candidates (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument    VARCHAR(20)  NOT NULL,
    structure     VARCHAR(50)  NOT NULL
                      CHECK (structure IN ('long_straddle','call_spread','put_spread','calendar_spread')),
    snapshot_time TIMESTAMPTZ  NOT NULL,
    edge_score    NUMERIC(6,4) NOT NULL CHECK (edge_score BETWEEN 0 AND 1),
    signals       JSONB        NOT NULL,
    generated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_backtest_candidates_snapshot_time
    ON backtest_candidates (snapshot_time DESC);

CREATE INDEX IF NOT EXISTS idx_backtest_candidates_instrument_edge
    ON backtest_candidates (instrument, edge_score DESC);

-- -----------------------------------------------------------------------------
-- backtest_outcomes
--
-- One row per (candidate, expiration) pair after the outcome has been resolved
-- by OutcomeTracker using yfinance history().
--
-- candidate_id FK to backtest_candidates.id (not strategy_candidates) —
-- live and backtest data never share FK relationships.
--
-- For long_straddle:
--   profitable = TRUE  if abs(underlying_close - entry_premium) > entry_premium
--   profitable = FALSE otherwise
--   profitable = NULL  if yfinance returned no data for the expiration date
--
-- For call_spread / put_spread (post-Sprint-A):
--   entry_premium, upper_strike, lower_strike are populated.
--   spread P&L formula deferred to the Sprint A follow-up / Sprint B extension.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backtest_outcomes (
    id               UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id     UUID          NOT NULL REFERENCES backtest_candidates(id),
    structure        VARCHAR(50)   NOT NULL
                         CHECK (structure IN ('long_straddle','call_spread','put_spread','calendar_spread')),
    expiration       TIMESTAMPTZ   NOT NULL,
    underlying_close NUMERIC(12,4) NOT NULL,
    -- Spread P&L fields (nullable — NULL for long_straddle)
    entry_premium    NUMERIC(12,4),
    upper_strike     NUMERIC(12,4),
    lower_strike     NUMERIC(12,4),
    -- NULL means outcome could not be determined (yfinance gap); row still inserted
    profitable       BOOLEAN,
    recorded_at      TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_backtest_outcomes_candidate_id
    ON backtest_outcomes (candidate_id);

CREATE INDEX IF NOT EXISTS idx_backtest_outcomes_expiration
    ON backtest_outcomes (expiration DESC);
