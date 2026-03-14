# Energy Options Opportunity Agent — User Guide

> **Version 1.0 • March 2026**
<<<<<<< HEAD
> This guide walks you through installing, configuring, and running the full pipeline end-to-end.
=======
> This guide walks you through setting up, configuring, and running the full Energy Options Opportunity Agent pipeline, then interpreting its output. It is written for developers who are comfortable with Python and the command line but are new to this project.
>>>>>>> fix/19-pr-87-hygiene-temp

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Setup & Configuration](#setup--configuration)
4. [Running the Pipeline](#running-the-pipeline)
5. [Interpreting the Output](#interpreting-the-output)
6. [Troubleshooting](#troubleshooting)

---

## Overview

<<<<<<< HEAD
The **Energy Options Opportunity Agent** is an autonomous, modular Python pipeline that identifies options trading opportunities driven by oil market instability. It ingests market data, supply signals, news events, and alternative datasets, then produces structured, ranked candidate options strategies.
=======
The Energy Options Opportunity Agent is an autonomous, modular pipeline that identifies options trading opportunities driven by oil market instability. It ingests market data, supply signals, news events, and alternative datasets, then produces structured, ranked candidate options strategies with full explainability.
>>>>>>> fix/19-pr-87-hygiene-temp

### What the pipeline does

```mermaid
flowchart LR
<<<<<<< HEAD
    A([Raw Feeds\nPrices · Options · News\nEIA · EDGAR · AIS]) --> B

    subgraph pipeline [Four-Agent Pipeline]
        direction LR
        B["🗄️ Data Ingestion Agent\nFetch & Normalize"]
        C["📡 Event Detection Agent\nSupply & Geo Signals"]
        D["⚙️ Feature Generation Agent\nDerived Signal Computation"]
        E["📊 Strategy Evaluation Agent\nOpportunity Ranking"]

        B -->|market state object| C
        C -->|scored events| D
        D -->|derived features| E
    end

    E --> F([Ranked Candidates\nJSON Output])
```

Data flows **unidirectionally** through four loosely coupled agents that share a market state object and a derived features store:

| Agent | Role | Key Outputs |
|---|---|---|
| **Data Ingestion** | Fetch & normalize | Unified market state object |
| **Event Detection** | Supply & geo signals | Confidence/intensity-scored events |
| **Feature Generation** | Derived signal computation | Volatility gaps, curve steepness, supply shock probability, etc. |
| **Strategy Evaluation** | Opportunity ranking | Ranked candidates with edge scores |

> **Advisory only.** The pipeline recommends strategies but does **not** execute trades automatically.
=======
    subgraph Ingestion ["① Data Ingestion Agent"]
        A1[Crude prices\nWTI · Brent]
        A2[ETF / Equity prices\nUSO · XLE · XOM · CVX]
        A3[Options chains\nIV · strike · expiry]
    end

    subgraph Events ["② Event Detection Agent"]
        B1[News & geo feeds\nGDELT · NewsAPI]
        B2[Supply / inventory\nEIA API]
        B3[Shipping & logistics\nMarineTraffic]
    end

    subgraph Features ["③ Feature Generation Agent"]
        C1[Volatility gap\nrealized vs implied]
        C2[Futures curve steepness]
        C3[Sector dispersion]
        C4[Insider conviction score]
        C5[Narrative velocity]
        C6[Supply shock probability]
    end

    subgraph Strategy ["④ Strategy Evaluation Agent"]
        D1[Rank candidates\nby edge score]
        D2[Explainability map\ncontributing signals]
    end

    RAW[(Raw market\nstate object)] --> Events
    Ingestion --> RAW
    RAW --> Features
    Events --> Features
    Features --> FEATS[(Derived\nfeatures store)]
    FEATS --> Strategy
    Strategy --> OUT[(JSON output\ncandidates)]
```

### In-scope instruments

| Category | Instruments |
|---|---|
| Crude futures | Brent Crude, WTI (`CL=F`) |
| ETFs | USO, XLE |
| Energy equities | Exxon Mobil (XOM), Chevron (CVX) |

### In-scope option structures (MVP)

| Structure | Enum value |
|---|---|
| Long straddle | `long_straddle` |
| Call spread | `call_spread` |
| Put spread | `put_spread` |
| Calendar spread | `calendar_spread` |

> **Note:** Automated trade execution is out of scope. The system is **advisory only**.
>>>>>>> fix/19-pr-87-hygiene-temp

---

## Prerequisites

### System requirements

| Requirement | Minimum |
|---|---|
<<<<<<< HEAD
| Python | 3.10+ |
| RAM | 2 GB |
| Disk | 10 GB (for 6–12 months of historical data) |
| OS | Linux, macOS, or Windows (WSL2 recommended) |
| Deployment target | Local machine, single VM, or container |

### Required accounts & API keys

All sources listed below are free or have a usable free tier. Obtain credentials before proceeding.

| Source | Used by | Sign-up URL |
|---|---|---|
| Alpha Vantage **or** MetalpriceAPI | Crude prices (WTI, Brent) | https://www.alphavantage.co / https://metalpriceapi.com |
| Yahoo Finance / yfinance | ETF & equity prices (USO, XLE, XOM, CVX) | No key required (public API) |
| Polygon.io | Options chains (strike, expiry, IV, volume) | https://polygon.io |
| EIA Open Data API | Supply/inventory data | https://www.eia.gov/opendata |
| GDELT / NewsAPI | News & geopolitical events | https://www.gdeltproject.org / https://newsapi.org |
| SEC EDGAR / Quiver Quant | Insider activity | https://www.sec.gov/cgi-bin/browse-edgar / https://www.quiverquant.com |
| MarineTraffic / VesselFinder | Shipping & tanker flows | https://www.marinetraffic.com / https://www.vesselfinderapi.com |
| Reddit / Stocktwits | Narrative & sentiment velocity | https://www.reddit.com/prefs/apps / https://stocktwits.com/developers |

### Python dependencies

Install all dependencies from the project root:

```bash
pip install -r requirements.txt
```

Core packages include:

```text
yfinance>=0.2
requests>=2.31
pandas>=2.0
numpy>=1.26
pydantic>=2.0
python-dotenv>=1.0
schedule>=1.2
```
=======
| Python | 3.10 or later |
| Operating system | Linux, macOS, or Windows (WSL recommended) |
| RAM | 2 GB |
| Disk | 10 GB free (for 6–12 months of historical data) |
| Network | Outbound HTTPS to external APIs |

### Python dependencies

Install dependencies from the project root:

```bash
pip install -r requirements.txt
```

Key packages the pipeline relies on:

| Package | Purpose |
|---|---|
| `yfinance` | ETF, equity, and options chain data |
| `requests` | REST calls to EIA, GDELT, NewsAPI, Alpha Vantage |
| `pandas` / `numpy` | Data normalization and feature computation |
| `schedule` (or `APScheduler`) | Cadence management for multi-frequency feeds |
| `pydantic` | Schema validation of the market state object and output |

### API credentials

You will need free-tier accounts and API keys for the following services before running the pipeline:

| Service | What it provides | Sign-up URL |
|---|---|---|
| Alpha Vantage | WTI / Brent spot & futures prices | <https://www.alphavantage.co/support/#api-key> |
| NewsAPI | Energy news headlines | <https://newsapi.org/register> |
| EIA Open Data | Inventory & refinery utilization | <https://www.eia.gov/opendata/register.php> |
| Polygon.io *(optional)* | Higher-fidelity options chains | <https://polygon.io> |
| Quiver Quant *(optional)* | Insider trade signals | <https://www.quiverquant.com> |

> `yfinance`, GDELT, SEC EDGAR, MarineTraffic free tier, and Reddit/Stocktwits do not require API keys for basic access.
>>>>>>> fix/19-pr-87-hygiene-temp

---

## Setup & Configuration

### 1. Clone the repository

```bash
git clone https://github.com/your-org/energy-options-agent.git
cd energy-options-agent
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
<<<<<<< HEAD
# .venv\Scripts\activate         # Windows (PowerShell)
=======
# .venv\Scripts\activate         # Windows
>>>>>>> fix/19-pr-87-hygiene-temp
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

<<<<<<< HEAD
### 4. Create the environment file

Copy the provided template and fill in your credentials:
=======
### 4. Configure environment variables

Copy the example environment file and fill in your credentials:
>>>>>>> fix/19-pr-87-hygiene-temp

```bash
cp .env.example .env
```

<<<<<<< HEAD
Then open `.env` in your editor and supply values for every variable described in the table below.

### Environment variables reference

All pipeline configuration is managed through environment variables. The `.env` file is loaded automatically at startup via `python-dotenv`.

#### Market data

| Variable | Required | Default | Description |
|---|---|---|---|
| `ALPHA_VANTAGE_API_KEY` | Yes* | — | API key for Alpha Vantage crude price feed |
| `METALPRICE_API_KEY` | Yes* | — | API key for MetalpriceAPI (alternative to Alpha Vantage) |
| `POLYGON_API_KEY` | Yes | — | Polygon.io key for options chain data |
| `USE_YAHOO_OPTIONS` | No | `false` | Set to `true` to fall back to Yahoo Finance for options data |

> \* Provide **one** of `ALPHA_VANTAGE_API_KEY` or `METALPRICE_API_KEY`.

#### Supply & inventory

| Variable | Required | Default | Description |
|---|---|---|---|
| `EIA_API_KEY` | Yes | — | EIA Open Data API key for inventory and refinery utilization |

#### News & geopolitical events

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEWSAPI_KEY` | Yes | — | NewsAPI key for headline ingestion |
| `GDELT_ENABLED` | No | `true` | Set to `false` to disable GDELT (no key required) |

#### Alternative signals

| Variable | Required | Default | Description |
|---|---|---|---|
| `QUIVER_API_KEY` | No | — | Quiver Quant API key for insider activity (Phase 3) |
| `MARINETRAFFIC_API_KEY` | No | — | MarineTraffic API key for tanker flow data (Phase 3) |
| `REDDIT_CLIENT_ID` | No | — | Reddit app client ID for sentiment feeds (Phase 3) |
| `REDDIT_CLIENT_SECRET` | No | — | Reddit app client secret (Phase 3) |
| `STOCKTWITS_ENABLED` | No | `false` | Set to `true` to enable Stocktwits sentiment (Phase 3) |

#### Pipeline behaviour

| Variable | Required | Default | Description |
|---|---|---|---|
| `PIPELINE_CADENCE_MINUTES` | No | `5` | How often the market data refresh cycle runs |
| `SLOW_FEED_CADENCE_HOURS` | No | `24` | Refresh interval for EIA and EDGAR feeds |
| `EDGE_SCORE_THRESHOLD` | No | `0.30` | Minimum edge score for a candidate to appear in output |
| `HISTORICAL_RETENTION_DAYS` | No | `365` | Days of raw and derived data to retain on disk |
| `OUTPUT_DIR` | No | `./output` | Directory where JSON output files are written |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `TZ` | No | `UTC` | Timezone for all timestamps; keep as `UTC` unless you have a specific reason |

### 5. Verify configuration

Run the built-in configuration check before starting the full pipeline:

```bash
python -m agent.cli check-config
=======
Open `.env` in your editor and set the values described in the table below.

#### Environment variable reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `ALPHA_VANTAGE_API_KEY` | ✅ | — | API key for crude price feeds (WTI, Brent) |
| `NEWS_API_KEY` | ✅ | — | API key for NewsAPI energy headline feed |
| `EIA_API_KEY` | ✅ | — | API key for EIA inventory & refinery data |
| `POLYGON_API_KEY` | ⬜ | — | Polygon.io key for higher-fidelity options chains |
| `QUIVER_QUANT_API_KEY` | ⬜ | — | Quiver Quant key for insider conviction signals |
| `DATA_STORE_PATH` | ⬜ | `./data` | Local directory for raw and derived historical data |
| `OUTPUT_PATH` | ⬜ | `./output` | Directory where JSON candidate files are written |
| `MARKET_DATA_INTERVAL_MINUTES` | ⬜ | `5` | Polling cadence for minute-level market feeds |
| `EIA_POLL_SCHEDULE` | ⬜ | `weekly` | Cadence for EIA inventory pulls (`daily` or `weekly`) |
| `EDGAR_POLL_SCHEDULE` | ⬜ | `daily` | Cadence for SEC EDGAR insider trade pulls |
| `HISTORICAL_RETENTION_DAYS` | ⬜ | `180` | Number of days of historical data to retain on disk |
| `MIN_EDGE_SCORE` | ⬜ | `0.20` | Candidates below this edge score are excluded from output |
| `LOG_LEVEL` | ⬜ | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

Example `.env` file:

```dotenv
# Required
ALPHA_VANTAGE_API_KEY=YOUR_KEY_HERE
NEWS_API_KEY=YOUR_KEY_HERE
EIA_API_KEY=YOUR_KEY_HERE

# Optional — leave blank to disable
POLYGON_API_KEY=
QUIVER_QUANT_API_KEY=

# Storage
DATA_STORE_PATH=./data
OUTPUT_PATH=./output

# Scheduler
MARKET_DATA_INTERVAL_MINUTES=5
EIA_POLL_SCHEDULE=weekly
EDGAR_POLL_SCHEDULE=daily
HISTORICAL_RETENTION_DAYS=180

# Scoring
MIN_EDGE_SCORE=0.20

# Logging
LOG_LEVEL=INFO
```

### 5. Initialise the data store

Run the initialisation script to create local directories and seed schema files:

```bash
python -m agent.init_store
>>>>>>> fix/19-pr-87-hygiene-temp
```

Expected output (all required keys present):

```
<<<<<<< HEAD
[OK] ALPHA_VANTAGE_API_KEY
[OK] POLYGON_API_KEY
[OK] EIA_API_KEY
[OK] NEWSAPI_KEY
[OK] GDELT_ENABLED = true
[--] QUIVER_API_KEY      (optional — Phase 3 signals disabled)
[--] MARINETRAFFIC_API_KEY (optional — Phase 3 signals disabled)
Configuration check passed. Ready to run.
=======
[INFO] Created data directory: ./data/raw
[INFO] Created data directory: ./data/derived
[INFO] Created output directory: ./output
[INFO] Store initialisation complete.
>>>>>>> fix/19-pr-87-hygiene-temp
```

If a required variable is missing, the check prints an error and exits with code `1`:

```
[FAIL] EIA_API_KEY is not set. Export the variable or add it to .env.
```

### 6. Initialise the data store

Create the local SQLite database and seed the schema:

```bash
python -m agent.cli init-db
```

This sets up tables for raw ingested data, derived features, detected events, and strategy candidates. Historical data is retained for the period defined by `HISTORICAL_RETENTION_DAYS`.

---

## Running the Pipeline

<<<<<<< HEAD
### Pipeline execution sequence

```mermaid
sequenceDiagram
    participant CLI as CLI / Scheduler
    participant DIA as Data Ingestion Agent
    participant EDA as Event Detection Agent
    participant FGA as Feature Generation Agent
    participant SEA as Strategy Evaluation Agent
    participant FS as Feature Store / DB
    participant OUT as output/*.json

    CLI->>DIA: trigger run
    DIA->>FS: write market state object
    DIA-->>CLI: ingestion complete

    CLI->>EDA: trigger run
    EDA->>FS: read market state
    EDA->>FS: write scored events
    EDA-->>CLI: detection complete

    CLI->>FGA: trigger run
    FGA->>FS: read market state + events
    FGA->>FS: write derived features
    FGA-->>CLI: features ready

    CLI->>SEA: trigger run
    SEA->>FS: read all features + events
    SEA->>OUT: write ranked candidates JSON
    SEA-->>CLI: evaluation complete
```

### Running a single full pipeline pass

Execute all four agents once in sequence:

```bash
python -m agent.cli run --once
```

You should see per-agent log lines followed by a summary:

```
2026-03-15T09:00:01Z [INFO] DataIngestionAgent  — fetched WTI=82.41, Brent=85.17
2026-03-15T09:00:03Z [INFO] DataIngestionAgent  — options chains loaded for USO, XLE, XOM, CVX
2026-03-15T09:00:04Z [INFO] EventDetectionAgent — 3 events detected (max intensity: 0.74)
2026-03-15T09:00:05Z [INFO] FeatureGenerationAgent — volatility_gap=positive, curve_steepness=contango
2026-03-15T09:00:06Z [INFO] StrategyEvaluationAgent — 5 candidates generated, top edge_score=0.71
2026-03-15T09:00:06Z [INFO] Output written → ./output/candidates_20260315T090006Z.json
```

### Running the pipeline continuously (scheduled mode)

Start the scheduler to refresh market data every `PIPELINE_CADENCE_MINUTES` minutes:

```bash
python -m agent.cli run --continuous
```

The scheduler runs the fast data cycle (prices, options) at the configured minutes-level cadence and the slow cycle (EIA, EDGAR) once every `SLOW_FEED_CADENCE_HOURS` hours. Press `Ctrl+C` to stop.

### Running individual agents

You can run any single agent in isolation for debugging or incremental testing:

```bash
# Data Ingestion only
python -m agent.cli run-agent ingestion

# Event Detection only (reads existing market state)
python -m agent.cli run-agent event-detection

# Feature Generation only (reads existing market state + events)
python -m agent.cli run-agent features

# Strategy Evaluation only (reads existing features)
python -m agent.cli run-agent strategy
```

### Running with Docker

A `Dockerfile` and `docker-compose.yml` are provided for container deployment:

```bash
# Build the image
docker build -t energy-options-agent:latest .

# Run with your .env file mounted
docker run --rm \
  --env-file .env \
  -v "$(pwd)/output:/app/output" \
  -v "$(pwd)/data:/app/data" \
  energy-options-agent:latest \
  python -m agent.cli run --continuous
```

Or use Compose:

```bash
docker compose up
```

### Phased activation

The pipeline supports four development phases. Enable phases progressively by setting the `PIPELINE_PHASE` variable:

```bash
# .env
PIPELINE_PHASE=2   # 1 | 2 | 3 | 4
```

| Phase | Name | Activated signals |
|---|---|---|
| `1` | Core Market Signals & Options | WTI/Brent prices, USO/XLE options surface, IV, long straddles, call/put spreads |
| `2` | Supply & Event Augmentation | + EIA inventory/refinery utilization, GDELT/NewsAPI event detection, supply disruption index |
| `3` | Alternative / Contextual Signals | + Insider trades (EDGAR/Quiver), narrative velocity (Reddit/Stocktwits), shipping data (MarineTraffic), cross-sector correlation |
| `4` | High-Fidelity Enhancements | + OPIS/regional pricing, exotic multi-legged structures *(deferred; see future roadmap)* |
=======
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
>>>>>>> fix/19-pr-87-hygiene-temp

---

## Interpreting the Output

### Output location

<<<<<<< HEAD
Each pipeline run writes a timestamped JSON file to `OUTPUT_DIR` (default `./output`):

```
output/
└── candidates_20260315T090006Z.json
```

The file contains an array of ranked strategy candidates sorted by `edge_score` descending.

### Output schema

| Field | Type | Description |
|---|---|---|
| `instrument` | string | Target instrument (e.g. `USO`, `XLE`, `CL=F`) |
| `structure` | enum | Options structure: `long_straddle` · `call_spread` · `put_spread` · `calendar_spread` |
| `expiration` | integer (days) | Target expiration in calendar days from the evaluation date |
| `edge_score` | float [0.0–1.0] | Composite opportunity score — higher = stronger signal confluence |
| `signals` | object | Map of contributing signals and their assessed values |
| `generated_at` | ISO 8601 datetime | UTC timestamp of candidate generation |

### Example output file
=======
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
>>>>>>> fix/19-pr-87-hygiene-temp

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
<<<<<<< HEAD
    "edge_score": 0.47,
    "signals": {
      "volatility_gap": "positive",
      "sector_dispersion": "high",
      "narrative_velocity": "stable"
=======
    "edge_score": 0.31,
    "signals": {
      "volatility_gap": "positive",
      "supply_shock_probability": "elevated",
      "sector_dispersion": "high"
>>>>>>> fix/19-pr-87-hygiene-temp
    },
    "generated_at": "2026-03-15T09:00:06Z"
  }
]
```

<<<<<<< HEAD
### Understanding the edge score

The `edge_score` is a composite float on the `[0.0, 1.0]` scale. It reflects the **confluence of contributing signals** — no single signal drives the score in isolation.

| Score range | Interpretation |
|---|---|
| `0.00 – 0.29` | Weak — below default threshold; not emitted unless threshold lowered |
| `0.30 – 0.49` | Moderate — some signal alignment; worth monitoring |
| `0.50 – 0.69` | Strong — meaningful signal confluence; higher-priority candidate |
| `0.70 – 1.00` | Very strong — high signal confluence; top-priority candidate |

>
=======
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
>>>>>>> fix/19-pr-87-hygiene-temp
