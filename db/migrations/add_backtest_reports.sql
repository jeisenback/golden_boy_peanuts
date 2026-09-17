-- =============================================================================
-- db/migrations/add_backtest_reports.sql
-- Issue #137 — Edge score validation harness
-- =============================================================================
--
-- Creates backtest_reports: persisted summaries of run_backtest() output.
-- One row per invocation of run_backtest(). report_json holds the full
-- serialized BacktestReport for audit purposes.
--
-- run_backtest() writes to this table in degraded-mode (log-and-continue on
-- failure), so a missing table never suppresses the return value to the caller.
--
-- HUMAN SIGN-OFF REQUIRED before running against any live DB.
-- Apply:  psql $DATABASE_URL -f db/migrations/add_backtest_reports.sql
-- Verify: \d backtest_reports
-- =============================================================================

CREATE TABLE IF NOT EXISTS backtest_reports (
    id                BIGSERIAL       PRIMARY KEY,
    period_start      TIMESTAMPTZ     NOT NULL,
    period_end        TIMESTAMPTZ     NOT NULL,
    lookback_days     INTEGER         NOT NULL,
    total_candidates  INTEGER         NOT NULL,
    outcomes_recorded INTEGER         NOT NULL,
    report_json       JSONB           NOT NULL,
    generated_at      TIMESTAMPTZ     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_backtest_reports_generated_at
    ON backtest_reports (generated_at DESC);
