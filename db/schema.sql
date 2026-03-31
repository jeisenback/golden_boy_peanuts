-- =============================================================================
-- db/schema.sql — Energy Options Opportunity Agent
-- Phase 1 + Phase 2 + Phase 3 schema
-- =============================================================================
--
-- Design principles (PRD Section 6.1):
--   - PostgreSQL 15+ in production; SQLite in unit tests only.
--   - All time-series tables use TIMESTAMPTZ (not TIMESTAMP) so that
--     TimescaleDB hypertable conversion requires zero SQL changes.
--   - Hypertable candidates (Phase 2, PRD Section 6.2):
--       * market_prices      → partition by timestamp
--       * options_chain      → partition by timestamp
--       * eia_inventory      → partition by fetched_at
--       * detected_events    → partition by detected_at
--   - Hypertable candidates (Phase 3, issue #148):
--       * insider_trades     → partition by trade_date
--       * shipping_events    → partition by timestamp
--       * narrative_signals  → partition by window_start
--
-- TimescaleDB migration triggers (PRD Section 6.2) — convert to hypertables
-- when ANY of the following conditions is met:
--   1. Historical data exceeds 6 months of tick-level market data.
--   2. Backtesting range queries consistently exceed 5 seconds.
--   3. Team size grows beyond a single contributor.
--
-- Migration script: db/migrate_timescaledb.sql (see issue #111)
--
-- Apply:  psql $DATABASE_URL -f db/schema.sql
-- Verify: \d market_prices    \d options_chain    \d feature_sets
--         \d strategy_candidates    \d strategy_outcomes    \d eia_inventory
--         \d detected_events    \d insider_trades   \d shipping_events
--         \d narrative_signals
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


-- -----------------------------------------------------------------------------
-- strategy_candidates
--
-- Stores generated strategy candidates from the Strategy Evaluation Agent.
-- Fields mirror PRD Section 9 output schema and are written by
-- `write_strategy_candidates()` as part of the Phase 1 pipeline.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS strategy_candidates (
    id            BIGSERIAL       PRIMARY KEY,
    instrument    TEXT            NOT NULL,
    structure     TEXT            NOT NULL CHECK (structure IN ('long_straddle','call_spread','put_spread','calendar_spread')),
    expiration    INTEGER         NOT NULL,
    edge_score    NUMERIC(5,4)    NOT NULL CHECK (edge_score BETWEEN 0 AND 1),
    signals       JSONB           NOT NULL,
    generated_at  TIMESTAMPTZ     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_strategy_candidates_generated_edge
    ON strategy_candidates (generated_at DESC, edge_score DESC);


-- -----------------------------------------------------------------------------
-- strategy_outcomes                                                 (Phase 3)
--
-- Stores actual price movement outcomes for strategy candidates (issue #130).
-- Closes the edge score feedback loop — without this table the edge score
-- heuristic has never been validated against real trade outcomes.
--
-- price_at_expiration and pct_move are nullable — populated by a separate job
-- that runs after expiration_date. The table is append-only; rows are never
-- deleted or edited (only the nullable columns are ever updated via upsert).
--
-- UNIQUE (candidate_id) ensures at most one outcome row per candidate.
-- ON CONFLICT DO UPDATE allows the expiration job to fill nullable columns
-- without inserting a duplicate.
--
-- Hypertable candidate: partition by generated_at.
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

CREATE INDEX IF NOT EXISTS idx_strategy_outcomes_candidate_id
    ON strategy_outcomes (candidate_id);

CREATE INDEX IF NOT EXISTS idx_strategy_outcomes_expiration_date
    ON strategy_outcomes (expiration_date DESC);


-- -----------------------------------------------------------------------------
-- feature_sets
--
-- Stores computed FeatureSet snapshots written by the Feature Generation Agent
-- (write_feature_set). volatility_gaps and feature_errors are JSONB arrays;
-- sector_dispersion is a coefficient of variation in [0.0, 1.0].
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feature_sets (
    id                BIGSERIAL       PRIMARY KEY,
    snapshot_time     TIMESTAMPTZ     NOT NULL,
    volatility_gaps   JSONB,
    sector_dispersion NUMERIC(10, 6),
    feature_errors    JSONB,
    computed_at       TIMESTAMPTZ     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feature_sets_snapshot_time
    ON feature_sets (snapshot_time DESC);


-- -----------------------------------------------------------------------------
-- eia_inventory
--
-- Stores weekly EIA petroleum status report records fetched by the Event
-- Detection Agent (fetch_eia_data). One row per reporting period (week).
-- UNIQUE on period ensures re-ingestion is idempotent (ON CONFLICT DO NOTHING).
-- Hypertable candidate: partition by fetched_at.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eia_inventory (
    id                          BIGSERIAL       PRIMARY KEY,
    period                      TEXT            NOT NULL,
    crude_stocks_mb             NUMERIC(12, 3),
    refinery_utilization_pct    NUMERIC(6, 3),
    source                      TEXT            NOT NULL DEFAULT 'eia',
    fetched_at                  TIMESTAMPTZ     NOT NULL,
    CONSTRAINT uq_eia_inventory_period UNIQUE (period)
);

CREATE INDEX IF NOT EXISTS idx_eia_inventory_period
    ON eia_inventory (period DESC);


-- -----------------------------------------------------------------------------
-- detected_events
--
-- Stores classified energy market events produced by the Event Detection Agent
-- (classify_event → write_detected_events). event_id is a deterministic hash
-- of the source URL — UNIQUE ensures re-classification is idempotent.
-- affected_instruments is a JSONB array of ticker strings.
-- Hypertable candidate: partition by detected_at.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS detected_events (
    id                      BIGSERIAL       PRIMARY KEY,
    event_id                TEXT            NOT NULL,
    event_type              TEXT            NOT NULL,
    description             TEXT            NOT NULL,
    source                  TEXT            NOT NULL,
    confidence_score        NUMERIC(5, 4)   NOT NULL,
    intensity               TEXT            NOT NULL,
    detected_at             TIMESTAMPTZ     NOT NULL,
    affected_instruments    JSONB,
    raw_headline            TEXT,
    CONSTRAINT uq_detected_events_event_id UNIQUE (event_id)
);

CREATE INDEX IF NOT EXISTS idx_detected_events_detected_at
    ON detected_events (detected_at DESC);


-- -----------------------------------------------------------------------------
-- insider_trades                                                     (Phase 3)
--
-- Stores SEC EDGAR Form 4 insider trade records fetched by
-- fetch_edgar_insider_trades() (issue #149), optionally enriched by
-- fetch_quiver_enrichment() (issue #150).
-- One row per trade filing. (instrument, officer_name, trade_date) is not
-- UNIQUE because the same officer may file multiple transactions on the same
-- day for the same instrument (e.g., multiple grants/sales in a single Form 4).
-- Hypertable candidate: partition by trade_date.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS insider_trades (
    id            BIGSERIAL       PRIMARY KEY,
    instrument    TEXT            NOT NULL,
    trade_date    TIMESTAMPTZ     NOT NULL,
    trade_type    TEXT            NOT NULL CHECK (trade_type IN ('buy', 'sell', 'grant', 'exercise')),
    shares        BIGINT,
    value_usd     NUMERIC(18, 2),
    officer_name  TEXT,
    source        TEXT            NOT NULL,
    fetched_at    TIMESTAMPTZ     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_insider_trades_instrument_trade_date
    ON insider_trades (instrument, trade_date DESC);


-- -----------------------------------------------------------------------------
-- shipping_events                                                    (Phase 3)
--
-- Stores tanker and vessel movement events fetched by fetch_tanker_flows()
-- (issue #153) from MarineTraffic or VesselFinder.
-- event_type examples: 'chokepoint_delay', 'route_deviation', 'anchored',
--   'port_call', 'ais_gap'.
-- Hypertable candidate: partition by timestamp.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shipping_events (
    id            BIGSERIAL       PRIMARY KEY,
    instrument    TEXT,                              -- affected energy instrument (nullable)
    vessel_id     TEXT            NOT NULL,
    event_type    TEXT            NOT NULL,
    latitude      NUMERIC(9, 6),
    longitude     NUMERIC(9, 6),
    timestamp     TIMESTAMPTZ     NOT NULL,
    source        TEXT            NOT NULL,
    fetched_at    TIMESTAMPTZ     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shipping_events_instrument_timestamp
    ON shipping_events (instrument, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_shipping_events_vessel_timestamp
    ON shipping_events (vessel_id, timestamp DESC);


-- -----------------------------------------------------------------------------
-- narrative_signals                                                  (Phase 3)
--
-- Stores social/news narrative velocity scores fetched by
-- fetch_reddit_sentiment() (issue #151) and
-- fetch_stocktwits_sentiment() (issue #152).
-- platform: 'reddit' | 'stocktwits' | 'combined'
-- sentiment: 'bullish' | 'bearish' | 'neutral' | 'mixed'
-- UNIQUE (instrument, platform, window_start) prevents duplicate ingestion
-- for the same time window — re-fetch uses ON CONFLICT DO NOTHING.
-- Hypertable candidate: partition by window_start.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS narrative_signals (
    id             BIGSERIAL       PRIMARY KEY,
    instrument     TEXT            NOT NULL,
    platform       TEXT            NOT NULL CHECK (platform IN ('reddit', 'stocktwits', 'combined')),
    score          NUMERIC(6, 4),                   -- normalized velocity score [0,1]
    mention_count  INTEGER,
    sentiment      TEXT            CHECK (sentiment IN ('bullish', 'bearish', 'neutral', 'mixed')),
    window_start   TIMESTAMPTZ     NOT NULL,
    window_end     TIMESTAMPTZ     NOT NULL,
    fetched_at     TIMESTAMPTZ     NOT NULL,
    CONSTRAINT uq_narrative_signals_instrument_platform_window
        UNIQUE (instrument, platform, window_start)
);

CREATE INDEX IF NOT EXISTS idx_narrative_signals_instrument_window
    ON narrative_signals (instrument, window_start DESC);
