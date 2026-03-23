-- =============================================================================
-- db/migrations/add_strategy_outcomes.sql
-- Issue #130 — Phase 3 strategy outcome tracking
-- =============================================================================
--
-- Creates the strategy_outcomes table to record actual price movement of the
-- underlying instrument after each strategy candidate expires.
--
-- Closes the edge score feedback loop: without this table the edge score
-- heuristic has never been validated against real trade outcomes.
--
-- Design notes:
--   - price_at_expiration and pct_move are nullable; populated by a separate
--     job that runs after expiration_date. The row is still inserted at
--     generation time so the pending-outcomes query can discover it.
--   - UNIQUE (candidate_id) ensures at most one outcome row per candidate.
--     ON CONFLICT DO UPDATE allows the expiration job to fill in the nullable
--     columns without inserting a duplicate.
--   - The table is append-only; rows are never deleted or edited (only
--     price_at_expiration / pct_move / recorded_at are ever updated).
--   - TIMESTAMPTZ everywhere → TimescaleDB hypertable conversion requires
--     zero SQL changes (partition by generated_at).
--
-- HUMAN SIGN-OFF REQUIRED before running against any live DB.
-- Apply:  psql $DATABASE_URL -f db/migrations/add_strategy_outcomes.sql
-- Verify: \d strategy_outcomes
-- =============================================================================

-- -----------------------------------------------------------------------------
-- strategy_outcomes
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS strategy_outcomes (
    id                  BIGSERIAL       PRIMARY KEY,
    candidate_id        BIGINT          NOT NULL REFERENCES strategy_candidates(id),
    instrument          TEXT            NOT NULL,
    structure           TEXT            NOT NULL
                            CHECK (structure IN ('long_straddle','call_spread','put_spread','calendar_spread')),
    generated_at        TIMESTAMPTZ     NOT NULL,
    expiration_date     TIMESTAMPTZ     NOT NULL,
    price_at_generation FLOAT           NOT NULL,
    price_at_expiration FLOAT,                       -- NULL until expiration job runs
    pct_move            FLOAT,                       -- NULL until expiration job runs
    recorded_at         TIMESTAMPTZ     NOT NULL,
    CONSTRAINT uq_strategy_outcomes_candidate UNIQUE (candidate_id)
);

-- Primary lookup: find outcome for a given candidate
CREATE INDEX IF NOT EXISTS idx_strategy_outcomes_candidate_id
    ON strategy_outcomes (candidate_id);

-- Expiration job scans: find outcomes due for price resolution
CREATE INDEX IF NOT EXISTS idx_strategy_outcomes_expiration_date
    ON strategy_outcomes (expiration_date DESC);
