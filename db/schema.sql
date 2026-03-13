-- =============================================================================
-- db/schema.sql — Energy Options Opportunity Agent
-- Phase 1 schema: Ingestion Agent tables
-- =============================================================================
--
-- Design principles (PRD Section 6.1):
--   - PostgreSQL 15+ in production; SQLite in unit tests only.
--   - All time-series tables use TIMESTAMPTZ (not TIMESTAMP) so that
--     TimescaleDB hypertable conversion requires zero SQL changes.
--   - Hypertable candidates (Phase 2, PRD Section 6.2):
--       * market_prices   → partition by timestamp
--       * options_chain   → partition by timestamp
--
-- TimescaleDB migration triggers (PRD Section 6.2) — convert to hypertables
-- when ANY of the following conditions is met:
--   1. Historical data exceeds 6 months of tick-level market data.
--   2. Backtesting range queries consistently exceed 5 seconds.
--   3. Team size grows beyond a single contributor.
--
-- Migration command (no schema changes required):
--   SELECT create_hypertable('market_prices', 'timestamp');
--   SELECT create_hypertable('options_chain', 'timestamp');
--
-- Apply:  psql $DATABASE_URL -f db/schema.sql
-- Verify: \d market_prices    \d options_chain
-- =============================================================================


-- -----------------------------------------------------------------------------
-- market_prices
--
-- Stores validated WTI, Brent, USO, XLE, XOM, and CVX price records written
-- by the Ingestion Agent (fetch_crude_prices, fetch_etf_equity_prices).
-- Hypertable candidate: partition by timestamp.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_prices (
    id              BIGSERIAL       PRIMARY KEY,
    instrument      TEXT            NOT NULL,
    instrument_type TEXT            NOT NULL,
    price           NUMERIC(18, 6)  NOT NULL,
    volume          BIGINT,
    source          TEXT            NOT NULL,
    timestamp       TIMESTAMPTZ     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_market_prices_instrument_timestamp
    ON market_prices (instrument, timestamp DESC);


-- -----------------------------------------------------------------------------
-- options_chain
--
-- Stores validated single-leg options records written by the Ingestion Agent
-- (fetch_options_chain) for USO, XLE, XOM, CVX.
-- Calendar spread legs are stored as individual rows.
-- Hypertable candidate: partition by timestamp.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS options_chain (
    id                  BIGSERIAL       PRIMARY KEY,
    instrument          TEXT            NOT NULL,
    strike              NUMERIC(18, 6)  NOT NULL,
    expiration_date     TIMESTAMPTZ     NOT NULL,
    implied_volatility  NUMERIC(10, 6),
    open_interest       BIGINT,
    volume              BIGINT,
    option_type         TEXT            NOT NULL
                            CHECK (option_type IN ('call', 'put')),
    source              TEXT            NOT NULL,
    timestamp           TIMESTAMPTZ     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_options_chain_instrument_expiration
    ON options_chain (instrument, expiration_date);
