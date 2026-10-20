-- =============================================================================
-- db/migrations/add_insider_filing_fields.sql
-- Follow-up to the #251 insider study audit, 2026-10-20 (dedicated issue pending)
-- =============================================================================
--
-- Adds three nullable columns to insider_trades:
--
--   filing_date   TIMESTAMPTZ  date EDGAR accepted the Form 4 (EFTS file_date).
--                              The earliest moment the trade was public. Backtests
--                              must key on this, not trade_date, which carries
--                              0–2 business days of look-ahead.
--   accession_no  TEXT         EDGAR accession number of the filing. The table has
--                              no natural key without it; enables dedup.
--   insider_role  TEXT         officerTitle, else director / ten_percent_owner /
--                              other, from reportingOwnerRelationship.
--
-- All three are NULL for Quiver rows and for rows ingested before this
-- migration. No existing column, constraint or index is changed.
--
-- HUMAN SIGN-OFF REQUIRED before running against any live DB.
-- Apply:  psql $DATABASE_URL -f db/migrations/add_insider_filing_fields.sql
-- Verify: \d insider_trades
-- =============================================================================

ALTER TABLE insider_trades ADD COLUMN IF NOT EXISTS filing_date  TIMESTAMPTZ;
ALTER TABLE insider_trades ADD COLUMN IF NOT EXISTS accession_no TEXT;
ALTER TABLE insider_trades ADD COLUMN IF NOT EXISTS insider_role TEXT;

CREATE INDEX IF NOT EXISTS idx_insider_trades_instrument_filing_date
    ON insider_trades (instrument, filing_date DESC);
