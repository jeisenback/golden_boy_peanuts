-- =============================================================================
-- db/migrations/add_strategy_outcomes.sql
-- Issue #130 — Sprint 9 Phase 3
-- =============================================================================
--
-- Adds the strategy_outcomes table to record actual price movements after each
-- strategy candidate is generated. This closes the feedback loop needed to
-- validate whether edge scores are predictive.
--
-- The table is append-only: outcomes are never deleted or edited.
-- price_at_expiration, pct_move are nullable — populated by a reconciliation
-- job after the candidate's expiration date passes.
--
-- HUMAN SIGN-OFF REQUIRED before running against any live DB.
-- Apply:  psql $DATABASE_URL -f db/migrations/add_strategy_outcomes.sql
-- Verify: \d strategy_outcomes
-- =============================================================================

CREATE TABLE IF NOT EXISTS strategy_outcomes (
    id                    BIGSERIAL       PRIMARY KEY,
    candidate_id          BIGINT          NOT NULL UNIQUE REFERENCES strategy_candidates(id),
    instrument            TEXT            NOT NULL,
    structure             TEXT            NOT NULL
                              CHECK (structure IN ('long_straddle','call_spread','put_spread','calendar_spread')),
    generated_at          TIMESTAMPTZ     NOT NULL,
    expiration_date       TIMESTAMPTZ     NOT NULL,
    price_at_generation   DOUBLE PRECISION NOT NULL,
    price_at_expiration   DOUBLE PRECISION,
    pct_move              DOUBLE PRECISION,
    recorded_at           TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_strategy_outcomes_candidate_id
    ON strategy_outcomes (candidate_id);

CREATE INDEX IF NOT EXISTS idx_strategy_outcomes_expiration_date
    ON strategy_outcomes (expiration_date DESC);

CREATE INDEX IF NOT EXISTS idx_strategy_outcomes_instrument
    ON strategy_outcomes (instrument, recorded_at DESC);
