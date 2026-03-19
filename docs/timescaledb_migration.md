# TimescaleDB Migration Guide

**Energy Options Opportunity Agent — PRD §6.2**

---

## Overview

The Energy Options Opportunity Agent uses PostgreSQL 15 for Phase 1. Phase 2
adds TimescaleDB — a PostgreSQL extension that converts regular tables into
hypertables (time-partitioned tables). This delivers faster time-range queries
for backtesting and long-lived market-data series with zero application code
changes.

Schema design guarantees zero-friction migration: all time-series tables already
use `TIMESTAMPTZ` columns, and no ORM or query changes are required. The
migration is a single-file SQL script applied once.

---

## Migration Triggers

**Run the migration when ANY of the following is true (PRD §6.2):**

| # | Trigger | How to check |
|---|---------|-------------|
| 1 | Historical data exceeds **6 months** of tick-level market data | `SELECT count(*), min(timestamp), max(timestamp) FROM market_prices;` |
| 2 | Backtesting range queries **consistently exceed 5 seconds** | Run a 30-day window query; `EXPLAIN ANALYZE SELECT ... WHERE timestamp BETWEEN ...` |
| 3 | Team size grows **beyond a single contributor** | Sprint planning / team roster |

---

## Tables Being Converted

| Table | Partition column | Data description |
|-------|-----------------|-----------------|
| `market_prices` | `timestamp` | WTI, Brent, USO, XLE, XOM, CVX tick prices |
| `options_chain` | `timestamp` | Options records for USO, XLE, XOM, CVX |
| `eia_inventory` | `fetched_at` | Weekly EIA petroleum status reports |
| `detected_events` | `detected_at` | Classified energy market events |

---

## Pre-Migration Checklist

Before running the migration script, confirm:

- [ ] PostgreSQL 15+ is running (`SELECT version();`)
- [ ] `db/schema.sql` has been applied: all four tables exist
  ```sql
  SELECT table_name FROM information_schema.tables
  WHERE table_name IN ('market_prices','options_chain','eia_inventory','detected_events');
  ```
- [ ] `docker-compose.yml` is using `timescale/timescaledb:2.15.2-pg15`
  (already updated — see Docker Compose section below)
- [ ] Database backup taken if live data is present
  ```bash
  pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql
  ```

---

## Step-by-Step Migration

### 1. Start the database (Docker Compose)

```bash
docker compose up -d
docker compose ps   # confirm db service is healthy
```

### 2. Apply the base schema (if not already applied)

```bash
psql $DATABASE_URL -f db/schema.sql
```

### 3. Apply the TimescaleDB migration

```bash
psql $DATABASE_URL -f db/migrate_timescaledb.sql
```

Expected output:

```
CREATE EXTENSION
create_hypertable
------------------
 (1,1)
(1 row)

create_hypertable
------------------
 (2,1)
(1 row)

create_hypertable
------------------
 (3,1)
(1 row)

create_hypertable
------------------
 (4,1)
(1 row)
```

If running against a database where the migration was already applied, each
`create_hypertable` call returns a `NOTICE` ("table is already a hypertable")
and exits successfully — the script is fully idempotent.

### 4. Verify

```sql
SELECT hypertable_name, num_dimensions, num_chunks
FROM timescaledb_information.hypertables;
```

Expected: 4 rows — `market_prices`, `options_chain`, `eia_inventory`, `detected_events`.

```bash
# Quick schema spot-check:
psql $DATABASE_URL -c "\d market_prices"
psql $DATABASE_URL -c "\d options_chain"
```

---

## Docker Compose

`docker-compose.yml` uses `timescale/timescaledb:2.15.2-pg15` — the TimescaleDB
image that bundles PostgreSQL 15 and the extension pre-installed. No additional
Docker changes are required before running the migration.

To restart with a clean database (development only — destroys all data):

```bash
docker compose down -v
docker compose up -d
psql $DATABASE_URL -f db/schema.sql
psql $DATABASE_URL -f db/migrate_timescaledb.sql
```

---

## Rollback Procedure

TimescaleDB does not provide a direct "undo hypertable" command. If you need to
revert the four tables to regular PostgreSQL tables:

**Step 1 — Back up data (before rolling back)**

```bash
psql $DATABASE_URL -c "\COPY market_prices    TO '/tmp/market_prices_bak.csv'    CSV HEADER"
psql $DATABASE_URL -c "\COPY options_chain    TO '/tmp/options_chain_bak.csv'    CSV HEADER"
psql $DATABASE_URL -c "\COPY eia_inventory    TO '/tmp/eia_inventory_bak.csv'    CSV HEADER"
psql $DATABASE_URL -c "\COPY detected_events  TO '/tmp/detected_events_bak.csv'  CSV HEADER"
```

**Step 2 — Drop the hypertables** (destructive — loses all data in the tables)

```sql
DROP TABLE market_prices;
DROP TABLE options_chain;
DROP TABLE eia_inventory;
DROP TABLE detected_events;
```

**Step 3 — Re-create as regular tables**

```bash
psql $DATABASE_URL -f db/schema.sql
```

**Step 4 — Re-import data**

```bash
psql $DATABASE_URL -c "\COPY market_prices    FROM '/tmp/market_prices_bak.csv'    CSV HEADER"
psql $DATABASE_URL -c "\COPY options_chain    FROM '/tmp/options_chain_bak.csv'    CSV HEADER"
psql $DATABASE_URL -c "\COPY eia_inventory    FROM '/tmp/eia_inventory_bak.csv'    CSV HEADER"
psql $DATABASE_URL -c "\COPY detected_events  FROM '/tmp/detected_events_bak.csv'  CSV HEADER"
```

**Step 5 — Drop the extension** (only if no other databases use TimescaleDB)

```sql
DROP EXTENSION IF EXISTS timescaledb CASCADE;
```

> **Warning:** Steps 2–3 are destructive. Always complete Step 1 first.

---

## References

- PRD §6.2 — TimescaleDB Migration
- PRD §12.7 — Coverage Gaps (migration plan flagged)
- `db/schema.sql` — base schema; all hypertable candidates annotated in header
- `db/migrate_timescaledb.sql` — idempotent migration script
- `docker-compose.yml` — `timescale/timescaledb:2.15.2-pg15` image
- [TimescaleDB docs: create_hypertable](https://docs.timescale.com/api/latest/hypertable/create_hypertable/)
