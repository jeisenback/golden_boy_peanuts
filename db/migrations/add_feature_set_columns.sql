-- =============================================================================
-- db/migrations/add_feature_set_columns.sql
-- Issue #173 — Sprint 9 Phase 3 Feature Generation DB Completeness
-- =============================================================================
--
-- Adds 5 missing NUMERIC columns to feature_sets table to support
-- persisting alternative data signals computed by the Feature Generation Agent:
--
--   futures_curve_steepness     NUMERIC(8,6)  — WTI futures curve slope (contango indicator)
--   supply_shock_probability    NUMERIC(6,4)  — Supply disruption risk [0, 1]
--   insider_conviction_score    NUMERIC(6,4)  — Insider trade conviction [0, 1]
--   narrative_velocity          NUMERIC(6,4)  — News/social acceleration [0, ∞)
--   tanker_disruption_index     NUMERIC(6,4)  — Maritime shipping disruption risk [0, 1]
--
-- All columns are nullable to maintain backward compatibility and allow
-- features to compute selectively (e.g., supply shock only if event detected).
--
-- HUMAN SIGN-OFF REQUIRED before running against any live DB.
-- Apply: psql $DATABASE_URL -f db/migrations/add_feature_set_columns.sql
-- Verify: \d feature_sets
-- =============================================================================

-- Add the 5 missing columns to feature_sets table.
-- IF NOT EXISTS prevents idempotent re-application.
ALTER TABLE feature_sets
ADD COLUMN IF NOT EXISTS futures_curve_steepness NUMERIC(8,6),
ADD COLUMN IF NOT EXISTS supply_shock_probability NUMERIC(6,4),
ADD COLUMN IF NOT EXISTS insider_conviction_score NUMERIC(6,4),
ADD COLUMN IF NOT EXISTS narrative_velocity NUMERIC(6,4),
ADD COLUMN IF NOT EXISTS tanker_disruption_index NUMERIC(6,4);

-- Optional: comment on the new columns for documentation
COMMENT ON COLUMN feature_sets.futures_curve_steepness
    IS 'WTI crude futures curve slope (positive = contango, negative = backwardation)';
COMMENT ON COLUMN feature_sets.supply_shock_probability
    IS 'Probability of supply disruption [0.0, 1.0]; NULL if not computed';
COMMENT ON COLUMN feature_sets.insider_conviction_score
    IS 'Conviction score from insider trading activity [0.0, 1.0]; NULL if no trades';
COMMENT ON COLUMN feature_sets.narrative_velocity
    IS 'Headline/social mention acceleration; higher = rising narrative momentum';
COMMENT ON COLUMN feature_sets.tanker_disruption_index
    IS 'Maritime shipping disruption risk [0.0, 1.0]; NULL if not computed';
