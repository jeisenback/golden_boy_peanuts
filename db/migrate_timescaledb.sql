-- =============================================================================
-- db/migrate_timescaledb.sql — TimescaleDB hypertable migration
-- Energy Options Opportunity Agent
-- =============================================================================
--
-- Purpose: Convert the four time-series partitioning candidates defined in
--   db/schema.sql to TimescaleDB hypertables.
--
-- Migration triggers (PRD §6.2) — run this script when ANY of the following:
--   1. Historical data exceeds 6 months of tick-level market data.
--   2. Backtesting range queries consistently exceed 5 seconds.
--   3. Team size grows beyond a single contributor.
--
-- Idempotency: All statements use IF NOT EXISTS / if_not_exists => TRUE.
--   Safe to run multiple times against the same database; existing hypertables
--   produce a NOTICE, not an error.
--
-- Pre-migration requirements:
--   - PostgreSQL 15+ running (matches docker-compose.yml: timescale/timescaledb:2.15.2-pg15)
--   - db/schema.sql already applied (all four tables must exist)
--   - TimescaleDB extension available in the PostgreSQL cluster
--
-- Apply:
--   psql $DATABASE_URL -f db/schema.sql          # if not already applied
--   psql $DATABASE_URL -f db/migrate_timescaledb.sql
--
-- Verify:
--   SELECT hypertable_name, num_dimensions FROM timescaledb_information.hypertables;
-- =============================================================================


-- Step 1: Enable the TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;


-- Step 2: Convert time-series tables to hypertables
--
-- market_prices — partition by timestamp (tick-level WTI, Brent, USO, XLE, XOM, CVX)
SELECT create_hypertable('market_prices', 'timestamp', if_not_exists => TRUE);

-- options_chain — partition by timestamp (tick-level options records)
SELECT create_hypertable('options_chain', 'timestamp', if_not_exists => TRUE);

-- eia_inventory — partition by fetched_at (weekly EIA petroleum status reports)
SELECT create_hypertable('eia_inventory', 'fetched_at', if_not_exists => TRUE);

-- detected_events — partition by detected_at (classified energy market events)
SELECT create_hypertable('detected_events', 'detected_at', if_not_exists => TRUE);


-- =============================================================================
-- ROLLBACK PROCEDURE
-- =============================================================================
--
-- TimescaleDB does not provide a direct "undo hypertable" command. To revert
-- a table from a hypertable back to a regular PostgreSQL table:
--
--   1. Export the data:
--        \COPY market_prices TO '/tmp/market_prices_backup.csv' CSV HEADER;
--        (repeat for each hypertable)
--
--   2. Drop the hypertable (this drops all chunks and data):
--        DROP TABLE market_prices;
--        DROP TABLE options_chain;
--        DROP TABLE eia_inventory;
--        DROP TABLE detected_events;
--
--   3. Re-create as regular tables (re-apply db/schema.sql):
--        psql $DATABASE_URL -f db/schema.sql
--
--   4. Re-import data:
--        \COPY market_prices FROM '/tmp/market_prices_backup.csv' CSV HEADER;
--        (repeat for each table)
--
--   5. Drop the extension (optional — only if no other databases use it):
--        DROP EXTENSION IF EXISTS timescaledb CASCADE;
--
-- WARNING: Steps 2–3 are destructive. Always back up data before rolling back.
-- =============================================================================
