```markdown
[Energy Options Opportunity Agent — User Guide]

Version: 1.0 — Mocked artifact (generated locally)

This developer-focused guide explains how to set up, configure, and run the Energy Options Opportunity Agent pipeline locally and in CI. It is a mocked output used for documentation and testing purposes — do not treat it as authoritative for production configuration. Use `scripts/run_doc_generation.py` to regenerate with the LLM when an API key is available.

---

## Table of contents

- Overview
- Prerequisites
- Setup & configuration
- Running the pipeline
- Output schema: `strategy_candidates`
- Troubleshooting & QA
- Regenerating this guide

---

## Overview

The Energy Options Opportunity Agent is a modular pipeline that ingests price, options, news, and supply signals, computes derived features and signals, and produces ranked candidate options strategies (Phase 1: long straddles, call spreads, put spreads). The pipeline is advisory only and does not execute trades.

Key pipeline agents (logical components):

- Data ingestion — fetches and normalizes feeds (prices, options, news, EIA, EDGAR).
- Event detection — surface supply/news events and assign confidence scores.
- Feature generation — compute volatility gaps, curve shape, and other derived signals.
- Strategy evaluation — score and rank `StrategyCandidate` objects and persist them.

## Prerequisites

- Python 3.10 or later
- Git and network access for external APIs
- Optional: Docker (for CI/integration tests)
- A working virtual environment (recommended)

Install runtime dependencies:

```bash
python -m venv .venv
.
source .venv/bin/activate  # macOS / Linux
# .venv\\Scripts\\activate   # Windows PowerShell
pip install -r requirements.txt
```

## Setup & configuration

1. Copy the example environment file and edit credentials:

```bash
cp .env.example .env
```

2. Minimum environment variables (example):

| Name | Required | Notes |
|---|---:|---|
| `ALPHA_VANTAGE_API_KEY` | ✅ | Crude price feed (or use an alternative) |
| `EIA_API_KEY` | ✅ | EIA supply & inventory data |
| `NEWS_API_KEY` | ✅ | Headline ingestion |
| `POLYGON_API_KEY` | ⬜ | Optional: improved options chains |

3. For doc-generation with the real LLM set `ANTHROPIC_API_KEY` (or chosen provider) in the environment before running `scripts/run_doc_generation.py`.

## Running the pipeline (developer mode)

Run the pipeline entrypoint or agent runner (examples depend on local CLI wiring in this repo):

```bash
# run a single evaluation cycle (development)
python -m agent.run --run-once

# run strategy evaluation unit (local)
python -m src.agents.strategy_evaluation.strategy_evaluation_agent
```

For CI/integration tests that rely on an ephemeral Postgres, set `CI=1` in the workflow and use the provided `.github` job definitions.

## Output schema: `strategy_candidates`

Phase 1 output schema (persisted to Postgres table `strategy_candidates`):

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PRIMARY KEY | Auto-increment ID |
| `instrument` | TEXT NOT NULL | e.g. `USO` |
| `structure` | TEXT NOT NULL | Enum: `long_straddle`, `call_spread`, `put_spread` |
| `expiration` | INTEGER NOT NULL | Unix timestamp or epoch day for expiry (see code comments) |
| `edge_score` | NUMERIC(5,4) NOT NULL | 0..1 normalized score |
| `signals` | JSONB NOT NULL | Signal breakdown used to compute the edge score |
| `generated_at` | TIMESTAMPTZ NOT NULL | UTC timestamp of candidate generation |

The repository includes an idempotent DDL at `db/schema.sql` which creates `strategy_candidates` with an index on `(generated_at DESC, edge_score DESC)`.

## Troubleshooting & QA

- No candidates produced: confirm API keys and `EDGE_SCORE_THRESHOLD` in `.env`.
- `HTTP 401` from feed: rotate/regenerate API key; never commit keys to Git.
- Integration tests failing locally: run with `CI=1` or use the workflow service containers defined in `.github/workflows`.

## Regenerating this guide (safe dev flow)

To regenerate using the project's doc-generation agent (requires an LLM key):

```bash
export ANTHROPIC_API_KEY="<your_key>"
export PYTHONPATH=.
python scripts/run_doc_generation.py --subject "full pipeline"
```

On Windows PowerShell:

```powershell
$env:ANTHROPIC_API_KEY = "<your_key>"
$env:PYTHONPATH = "."
python scripts/run_doc_generation.py --subject "full pipeline"
```

The script writes Markdown artifacts to `docs/generated/` by default.

---

Security note: this mocked guide intentionally includes no real secrets. Do not paste API keys, tokens, or private credentials into docs files.

If you'd like, I can (a) run the real generator once you export `ANTHROPIC_API_KEY` here, or (b) open a PR replacing the generated file with this mocked content. Which would you prefer?

This sets up tables for raw ingested data, derived features, detected events, and strategy candidates. Historical data is retained for the period defined by `HISTORICAL_RETENTION_DAYS`.

---

## Running the Pipeline

### Pipeline execution modes

The pipeline supports two modes:

| Mode | Command | Use case |
|---|---|---|
| **Single run** | `python -m agent.run --once` | Ad-hoc evaluation; runs each agent once and exits |
| **Continuous** | `python -m agent.run` | Scheduled daemon; respects cadence settings in `.env` |

### Single run (recommended for first-time setup)

```bash
python -m agent.run --once
```

This executes all four agents in sequence:

```
[INFO] [1/4] Data Ingestion Agent — fetching market state...
[INFO] [2/4] Event Detection Agent — scanning news and supply feeds...
[INFO] [3/4] Feature Generation Agent — computing derived signals...
[INFO] [4/4] Strategy Evaluation Agent — ranking candidates...
[INFO] Output written to: ./output/candidates_2026-03-15T14:32:00Z.json
```

### Continuous / scheduled run

```bash
python -m agent.run
```

The scheduler honours the cadence settings from `.env`:

| Feed layer | Default cadence |
|---|---|
| Crude prices, ETF / equity prices | Every 5 minutes |
| Options chains | Daily |
| EIA inventory | Weekly |
| SEC EDGAR insider activity | Daily |
| GDELT / NewsAPI | Continuous / daily |
| Shipping / narrative sentiment | Continuous |

Press `Ctrl+C` to stop the daemon gracefully.

### Running individual agents

Each agent can be run independently for development or debugging:

```bash
# Data Ingestion Agent only
python -m agent.ingestion

# Event Detection Agent only
python -m agent.events

# Feature Generation Agent only
python -m agent.features

# Strategy Evaluation Agent only
python -m agent.strategy
```

> **Dependency note:** Each agent reads from the shared market state object written by the preceding agent. Run them out of order only when a valid state file already exists in `DATA_STORE_PATH`.

### Targeting a specific MVP phase

Pass the `--phase` flag to limit which signal layers are active:

```bash
python -m agent.run --once --phase 1   # Core market signals and options only
python -m agent.run --once --phase 2   # Adds EIA supply and event detection
python -m agent.run --once --phase 3   # Adds insider, narrative, and shipping
```

Phase 4 enhancements (OPIS pricing, exotic structures, automated execution) are not yet implemented in the MVP.

---

## Interpreting the Output

### Output location

Each pipeline run writes one JSON file to `OUTPUT_PATH`:

```
./output/candidates_2026-03-15T14:32:00Z.json
```

### Output schema

Each file contains an array of candidate objects. The fields are:

| Field | Type | Description |
|---|---|---|
| `instrument` | `string` | Target instrument, e.g. `USO`, `XLE`, `CL=F` |
| `structure` | `enum` | One of `long_straddle`, `call_spread`, `put_spread`, `calendar_spread` |
| `expiration` | `integer` | Target expiration in calendar days from evaluation date |
| `edge_score` | `float [0.0–1.0]` | Composite opportunity score; higher = stronger signal confluence |
| `signals` | `object` | Map of contributing signals and their observed state |
| `generated_at` | `ISO 8601 datetime` | UTC timestamp of candidate generation |

### Example output

```json
[
  {
    "instrument": "USO",
    "structure": "long_straddle",
    "expiration": 30,
    "edge_score": 0.71,
    "signals": {
      "tanker_disruption_index": "high",
      "volatility_gap": "positive",
      "narrative_velocity": "rising",
      "supply_shock_probability": "elevated"
    },
    "generated_at": "2026-03-15T09:00:06Z"
  },
  {
    "instrument": "XLE",
    "structure": "call_spread",
    "expiration": 45,
    "edge_score": 0.31,
    "signals": {
      "volatility_gap": "positive",
      "supply_shock_probability": "elevated",
      "sector_dispersion": "high"
    },
    "generated_at": "2026-03-15T09:00:06Z"
  }
]
```

### Reading the edge score

| Edge score range | Interpretation |
|---|---|
| `0.70 – 1.00` | Strong signal confluence — high-priority candidate |
| `0.45 – 0.69` | Moderate confluence — worth monitoring |
| `0.20 – 0.44` | Weak confluence — low priority |
| `< 0.20` | Below threshold — excluded from output by default |

The `MIN_EDGE_SCORE` environment variable controls the exclusion threshold.

### Reading the signals map

Each key in the `signals` object corresponds to a derived feature computed by the Feature Generation Agent:

| Signal key | Source agent | What it means |
|---|---|---|
| `volatility_gap` | Feature Generation | Realized vol exceeds (`positive`) or trails (`negative`) implied vol |
| `futures_curve_steepness` | Feature Generation | Degree of contango or backwardation in the crude curve |
| `sector_dispersion` | Feature Generation | Spread between energy sub-sector returns |
| `insider_conviction_score` | Feature Generation | Aggregated insider buying/selling intensity from EDGAR |
| `narrative_velocity` | Feature Generation | Acceleration of energy-related headlines and social mentions |
| `supply_shock_probability` | Feature Generation | Composite probability of a near-term supply disruption |
| `tanker_disruption_index` | Event Detection | Severity of detected shipping chokepoint events |
| `refinery_outage_flag` | Event Detection | Active refinery outage detected (`true` / `false`) |
| `geopolitical_intensity` | Event Detection | Confidence-weighted geopolitical event score |

### Consuming output downstream

The JSON format is compatible with any JSON-capable dashboard or tool. To load candidates into a thinkorswim-compatible workflow, point its watchlist import or custom script at the file path configured in `OUTPUT_PATH`.

---

## Troubleshooting

### Common errors and fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| `KeyError: ALPHA_VANTAGE_API_KEY` | `.env` not loaded or variable missing | Confirm `.env` exists in the project root and contains the key; re-run `source .venv/bin/activate` |
| `HTTP 429 Too Many Requests` on Alpha Vantage | Free-tier rate limit exceeded | Increase `MARKET_DATA_INTERVAL_MINUTES` (e.g. to `15`) |
| `HTTP 401 Unauthorized` on any feed | Invalid or expired API key | Regenerate the key in the provider's dashboard and update `.env` |
| Options chain returns empty DataFrame | Yahoo Finance / Polygon outage or stale expiry | Run `--once` again after a few minutes; check provider status page |
| Pipeline exits with `DataStoreNotInitialised` | `init_store` was not run | Run `python -m agent.init_store` before the first pipeline run |
| All candidates have `edge_score < MIN_EDGE_SCORE` | Low volatility environment or missing signal layers | Lower `MIN_EDGE_SCORE` temporarily, or confirm Phase 2/3 feeds are active |
| `FileNotFoundError` writing output | `OUTPUT_PATH` directory does not exist | Run `python -m agent.init_store` or create the directory manually |
| Feature Generation Agent fails with `NaN` values | Delayed or missing upstream data | This is expected behaviour — the pipeline tolerates missing data and continues; check `LOG_LEVEL=DEBUG` for detail |
| Stale candidates (old `generated_at` timestamps) | Scheduler stopped or feed timeout | Restart with `python -m agent.run`; check network connectivity to API endpoints |

### Enabling debug

Enable `LOG_LEVEL=DEBUG` and review the agent logs for per-step diagnostics.

````
