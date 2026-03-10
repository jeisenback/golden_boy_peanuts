**Product Requirements Document**

Energy Options Opportunity Agent

Version 1.1 • March 2026 • Updated to reflect ESOD decisions

+-----------------------------------------------------------------------+
| **What Changed in v1.1**                                              |
|                                                                       |
| This version updates the original PRD to reflect decisions made in    |
| the Engineering Statement of Direction (ESOD v1.0):                   |
|                                                                       |
| • Data storage: SQLite replaced with PostgreSQL (MVP) → TimescaleDB   |
| (growth path). SQLite retained for local dev/test only.               |
|                                                                       |
| • Agent tooling: LangChain/LangGraph explicitly scoped as development |
| tooling only, not runtime dependencies.                               |
|                                                                       |
| • Operational requirements updated to reflect PostgreSQL baseline and |
| migration trigger criteria.                                           |
+-----------------------------------------------------------------------+

**1. Product Overview**

A system that identifies potential options opportunities driven by oil
market instability. The system ingests market data, supply signals, news
events, and alternative datasets to produce structured, ranked candidate
options strategies.

Initially designed for an individual contributor, the system is
architected for growth: additional instruments, multi-user access, and
cloud deployment are all on the horizon. It emphasizes low-cost,
low-overhead data feeds and a modular agent design.

**2. Objectives**

-   Detect volatility mispricing in oil-related instruments.

-   Rank candidate options structures by a computed edge score.

-   Maintain full explainability of all recommendations.

-   Enable incremental integration of alternative signals and expanded
    datasets.

**3. Scope**

**3.1 In-Scope Instruments**

-   Crude futures: Brent Crude, WTI

-   ETFs: USO, XLE

-   Energy equities: Exxon Mobil (XOM), Chevron (CVX)

**3.2 In-Scope Option Structures (MVP)**

-   Long straddles

-   Call / put spreads

-   Calendar spreads

**3.3 Out-of-Scope (Initially)**

-   Exotic or multi-legged options strategies

-   Regional refined product pricing (OPIS)

-   Automated trade execution

**4. Functional Requirements**

**4.1 Data Ingestion & Normalization**

-   Fetch and normalize crude prices, ETFs, energy equities, and options
    chains.

-   Convert disparate feeds into a unified market state object.

-   Store historical data for volatility and curve calculations.

**4.2 Event Detection**

-   Identify supply disruptions, refinery outages, tanker chokepoints,
    and geopolitical events.

-   Assign confidence and intensity scores to each detected event.

**4.3 Feature Generation**

Compute the following derived signals:

-   Volatility gaps (realized vs. implied)

-   Futures curve steepness

-   Sector dispersion

-   Insider conviction scores

-   Narrative velocity / headline acceleration

-   Supply shock probability

**4.4 Strategy Generation**

-   Evaluate eligible option structures based on computed signals.

-   Generate ranked opportunities with an edge score.

-   Include references to contributing signals for explainability.

**4.5 Output**

-   Structured output per candidate: instrument, option structure,
    expiration, edge score, contributing signals.

-   JSON-compatible format suitable for thinkorswim or other
    visualization tools.

**5. Non-Functional Requirements**

-   **Tolerate delayed or missing data without pipeline failure. All
    external API calls must implement retry logic and degraded-mode
    output.**Resilience:

-   **Market data refreshed on a minutes-level cadence; slower feeds
    (EIA, EDGAR) on daily/weekly schedules.**Latency:

-   **Persist historical raw and derived data for 6--12 months to
    support backtesting.**Retention:

-   **Agents for data ingestion, feature generation, event detection,
    and strategy evaluation are independently deployable.**Modularity:

-   **Lightweight footprint; runnable on local hardware in Phase 1.
    Designed for cloud migration in Phase 2+.**Deployment:

-   **Storage layer must support fast time-series range queries for
    backtesting. See data storage requirements below.**Query
    Performance:

**6. Data Storage Requirements**

+-----------------------------------------------------------------------+
| **Updated in v1.1**                                                   |
|                                                                       |
| Storage requirements updated from SQLite to a PostgreSQL →            |
| TimescaleDB migration path, reflecting ESOD decisions driven by       |
| backtesting performance requirements and the multi-user/cloud growth  |
| trajectory.                                                           |
+-----------------------------------------------------------------------+

**6.1 Phase 1 --- PostgreSQL 15+**

The MVP data store is PostgreSQL 15+. All schema design and query
patterns must be written for TimescaleDB compatibility from day one to
ensure a zero-friction migration.

-   Structured storage for market data, derived features, and strategy
    candidates.

-   Multi-user and cloud-ready from initial deployment.

-   SQLite permitted for local unit testing and offline development only
    --- never in staging or production.

**6.2 Phase 2 --- TimescaleDB Migration**

Migrate to TimescaleDB (a PostgreSQL extension) when any of the
following triggers are met:

-   Historical data exceeds 6 months of tick-level market data.

-   Backtesting range queries consistently exceed 5 seconds.

-   Team size grows beyond a single contributor.

TimescaleDB requires no SQL re-tooling, no ORM changes, and no data
model redesign --- only the addition of the extension and conversion of
relevant tables to hypertables. Migration path must be documented before
Phase 2 begins.

**7. Agent Tooling Requirements**

+-----------------------------------------------------------------------+
| **Updated in v1.1**                                                   |
|                                                                       |
| Agent tooling scope clarified to reflect ESOD decision: LangChain and |
| LangGraph are development-time tools only and must not be runtime     |
| dependencies.                                                         |
+-----------------------------------------------------------------------+

-   LangChain / LangGraph are used to accelerate agent scaffolding and
    development. They are not runtime dependencies.

-   All pipeline components must operate correctly without LangChain or
    LangGraph installed at runtime.

-   LLM calls must be routed through a provider-agnostic wrapper module.
    Direct provider client instantiation in pipeline code is prohibited.

**8. Data Sources**

All data sources are free or low-cost to minimize operational overhead.
The table below summarizes each layer, source, cost, update frequency,
and the data it provides.

  -------------------------------------------------------------------------------------------------
  **Layer**             **Source**      **Cost**       **Frequency**   **Notes**
  --------------------- --------------- -------------- --------------- ----------------------------
  Crude Prices          Alpha Vantage / Free           Minutes         WTI, Brent spot/futures
                        MetalpriceAPI                                  

  ETF/Equity Prices     Yahoo Finance / Free           Minutes         USO, XLE, Exxon, Chevron
                        yfinance                                       

  Options Data          Yahoo Finance / Free/Limited   Daily           Strike, expiry, IV, volume
                        Polygon.io                                     

  Supply/Inventory      EIA API         Free           Weekly          Inventories, refinery
                                                                       utilization

  News & Geo Events     GDELT / NewsAPI Free           Cont. / Daily   Energy disruptions,
                                                                       sanctions

  Insider Activity      SEC EDGAR /     Free/Limited   Daily           Executive trades
                        Quiver Quant                                   

  Shipping/Logistics    MarineTraffic / Free tier      Continuous      Tanker flows
                        VesselFinder                                   

  Narrative/Sentiment   Reddit /        Free           Continuous      Retail / news sentiment
                        Stocktwits                                     velocity
  -------------------------------------------------------------------------------------------------

**9. Candidate Output Schema**

Each strategy candidate is emitted as a structured object with the
following fields:

  --------------------------------------------------------------------------
  **Field**          **Type**        **Description**
  ------------------ --------------- ---------------------------------------
  **instrument**     string          Target instrument, e.g. USO, XLE, CL=F
                                     (WTI)

  **structure**      enum            long_straddle \| call_spread \|
                                     put_spread \| calendar_spread

  **expiration**     integer (days)  Target expiration in calendar days from
                                     evaluation date

  **edge_score**     float           Composite opportunity score; higher =
                     \[0.0--1.0\]    stronger signal confluence

  **signals**        object          Contributing signal map, e.g. {
                                     tanker_disruption_index: high,
                                     volatility_gap: positive }

  **generated_at**   ISO 8601        UTC timestamp of candidate generation
                     datetime        
  --------------------------------------------------------------------------

Example candidate:

> { \"instrument\": \"USO\", \"structure\": \"long_straddle\",
> \"expiration\": 30,
>
> \"edge_score\": 0.47, \"signals\": { \"tanker_disruption_index\":
> \"high\",
>
> \"volatility_gap\": \"positive\", \"narrative_velocity\": \"rising\" }
> }

**10. MVP Phasing**

Development is structured in four phases, allowing early delivery of
core value while deferring complexity to later iterations.

  --------------------------------------------------------------------------
  **Phase**   **Name**            **Scope**
  ----------- ------------------- ------------------------------------------
  **Phase 1** **Core Market       Crude benchmarks (WTI, Brent), USO/XLE
              Signals & Options** prices; options surface analysis (IV,
                                  strike distribution); strategy generator
                                  for long straddles and call/put spreads;
                                  output: ranked candidate opportunities.

  **Phase 2** **Supply & Event    EIA inventory and refinery utilization;
              Augmentation**      event detection via GDELT/NewsAPI; supply
                                  disruption indices; event-driven scoring
                                  in edge computation.

  **Phase 3** **Alternative /     Insider trades (EDGAR/Quiver); narrative
              Contextual          velocity (Reddit/Stocktwits); shipping
              Signals**           data (MarineTraffic); cross-sector
                                  correlation agent; full-layer edge
                                  scoring.

  **Phase 4** **Optional /        OPIS or regional refined pricing (paid);
              High-Fidelity       exotic/multi-legged option structures;
              Enhancements**      automated execution integration (out of
                                  scope for current horizon).
  --------------------------------------------------------------------------

**11. Operational Requirements**

-   Phase 1 deployment: local hardware. Phase 2+: cloud-ready (schema
    and infra designed for migration from day one).

-   Historical data storage sized for 6--12 months minimum to support
    backtesting.

-   Data store: PostgreSQL (Phase 1) → TimescaleDB (Phase 2). See
    Section 6 for migration triggers.

-   Agent framework (LangChain/LangGraph) used for development only. Not
    a production runtime dependency.

-   Output compatible with thinkorswim platform or any JSON-capable
    dashboard.

-   No automated trade execution in MVP; system is advisory only.

**12. Issue Map**

Cross-reference between PRD requirements and GitHub Issues. Each issue
is listed with its number, milestone, and implementation status. Use
this section to verify coverage and identify gaps before starting a
sprint.

+-----------------------------------------------------------------------+
| **Start Here — Issue #1 First**                                       |
|                                                                       |
| #1 (Initialize GitHub repository: labels, milestones, branch          |
| protection) must complete before any branch-based work begins.        |
| Branch protection on develop and main gates all PRs. No agent         |
| should open a branch until #1 is closed.                              |
+-----------------------------------------------------------------------+

**12.1 Phase -1 — Agent Workflow Readiness (Milestone 7)**

Prerequisites for agents to execute sprint work reliably. Must complete
before or alongside Phase 0. All issues in this section depend on #1.

  ---------------------------------------------------------------------------
  **Issue**   **Title**                                         **Owner**
  ----------- ------------------------------------------------- ------------
  #26         Fix ingestion_agent.py scaffold — add             Agent
              fetch_options_chain() stub, orphaned import,
              module-level logging

  #27         Add src/pipeline.py stub with run_pipeline()      Agent
              call sequence

  #28         Specify event_id generation in classify_event()   Human decides
              docstring                                         strategy first,
                                                               then Agent

  #29         Add tests/conftest.py with shared Pydantic        Agent
              model fixtures

  #30         Add pytest to local_check.sh quality gate         Agent

  #31         Make post_session.sh active — invoke              Agent
              local_check.sh + git diff --stat

  #32         Add ADLC startup step to CLAUDE.md session        Agent
              startup sequence

  #33         Document non-interactive branch creation          Agent
              fallback in CLAUDE.md and new_branch.sh

  #34         Replace inline @retry with @with_retry()          Agent
              after Issue #4 (BLOCKED by #4)
  ---------------------------------------------------------------------------

**12.2 Phase 0 — Project Setup (Milestone 1)**

Implements PRD §5 (resilience NFRs via shared retry), §6.1 (PostgreSQL
baseline), §11 (local deployment). All issues depend on #1.

  ---------------------------------------------------------------------------
  **Issue**   **Title**                               **PRD Section**
  ----------- --------------------------------------- -----------------------
  #1          Initialize GitHub repository            §11 Operational
              ← MUST COMPLETE BEFORE ALL OTHER ISSUES

  #2          Docker Compose for Postgres, venv,      §6.1 Data Storage
              .env setup

  #3          Extract shared get_engine() to          §6.1 Data Storage,
              src/core/db.py                          §5 Modularity

  #4          Extract shared retry config to          §5 Resilience,
              src/core/retry.py                       §7 Agent Tooling

  #5          CI pipeline verification                §7 Agent Tooling
  ---------------------------------------------------------------------------

**12.3 Phase 1 — Core Market Signals & Options (Milestone 2)**

Implements PRD §4.1 (ingestion), §4.3 (volatility + dispersion),
§4.4 (strategy generation), §4.5 (output schema), §8 (crude/ETF/options
data sources), §9 (candidate output schema).

*Schema (must complete before any agent implementation):*

  ---------------------------------------------------------------------------
  **Issue**   **Title**                               **PRD Section**
  ----------- --------------------------------------- -----------------------
  #6          PostgreSQL schema: market_prices and    §4.1, §6.1, §8
              options_chain tables

  #7          PostgreSQL schema: feature_sets and     §4.3, §4.4, §6.1
              strategy_candidates tables
  ---------------------------------------------------------------------------

*Ingestion Agent — blocked until #2, #3, #6 close:*

  ---------------------------------------------------------------------------
  **Issue**   **Title**                               **PRD Section**
  ----------- --------------------------------------- -----------------------
  #8          Implement fetch_crude_prices —          §4.1, §8 Crude
              Alpha Vantage (WTI, Brent)              Prices

  #9          Implement fetch_etf_equity_prices —     §4.1, §8 ETF/Equity
              yfinance (USO, XLE, XOM, CVX)           Prices

  #10         Implement fetch_options_chain —         §4.1, §8 Options
              yfinance / Polygon                      Data

  #11         Implement run_ingestion —               §4.1, §5 Resilience
              orchestration, MarketState, DB persist

  #12         QA: Ingestion Agent — integration       §4.1, §5 Retention
              test and coverage sign-off
  ---------------------------------------------------------------------------

*Feature Generation Agent — blocked until #3, #6, #7 close:*

  ---------------------------------------------------------------------------
  **Issue**   **Title**                               **PRD Section**
  ----------- --------------------------------------- -----------------------
  #13         Implement compute_volatility_gap —      §4.3 Volatility
              realized vs. implied volatility         Gaps

  #14         Implement compute_sector_dispersion —   §4.3 Sector
              price spread across XOM, CVX, USO, XLE  Dispersion

  #15         Implement run_feature_generation —      §4.3, §5 Resilience
              Phase 1 orchestration

  #16         QA: Feature Generation Agent            §4.3
  ---------------------------------------------------------------------------

+-----------------------------------------------------------------------+
| **Phase 1 Gap — Futures Curve Steepness**                            |
|                                                                       |
| PRD §4.3 lists futures curve steepness as a required signal.         |
| FeatureSet.futures_curve_steepness exists as an optional field        |
| (None acceptable in Phase 1). No Phase 1 implementation issue        |
| exists. Confirm with human lead: defer to Phase 2, or add a          |
| Phase 1 issue to compute slope from WTI spot vs. near-month          |
| futures prices available via Alpha Vantage.                           |
+-----------------------------------------------------------------------+

+-----------------------------------------------------------------------+
| **Phase 1 Note — Event Detection**                                   |
|                                                                       |
| run_feature_generation() accepts events: list[DetectedEvent] but     |
| event detection is Phase 2 scope (PRD §10). In Phase 1, Issue #15    |
| must pass events=[] explicitly. This must be documented in the        |
| Issue #15 acceptance criteria to prevent agent confusion.             |
+-----------------------------------------------------------------------+

*Strategy Evaluation Agent — blocked until #7, #15 close:*

  ---------------------------------------------------------------------------
  **Issue**   **Title**                               **PRD Section**
  ----------- --------------------------------------- -----------------------
  #17         Implement compute_edge_score — Phase 1  §4.4, §9
              static heuristic scoring

  #18         Implement evaluate_strategies —         §4.4, §3.2, §9
              long straddle, call spread, put spread

  #19         QA: Strategy Evaluation Agent           §4.4, §9
  ---------------------------------------------------------------------------

*Integration and Release — blocked until #12, #16, #19 close:*

  ---------------------------------------------------------------------------
  **Issue**   **Title**                               **PRD Section**
  ----------- --------------------------------------- -----------------------
  #20         Full pipeline integration test +        §4.5, §9, §5
              golden dataset validation

  #21         UAT: Phase 1 end-to-end validation      §4.5, §11
              against live market data

  #22         Phase 1 release: tag v0.1.0             §10 Phase 1
  ---------------------------------------------------------------------------

**12.4 Phase 2 — Supply & Event Augmentation (Milestone 3)**

Implements PRD §4.2 (event detection), §4.3 (supply shock probability),
§8 (EIA, GDELT/NewsAPI data sources). Issues to be defined in #23.

  ---------------------------------------------------------------------------
  **Issue**   **Title**                               **PRD Section**
  ----------- --------------------------------------- -----------------------
  #23         Phase 2 planning: define issues         §4.2, §8 Supply,
                                                      §10 Phase 2
  ---------------------------------------------------------------------------

**12.5 Phase 3 — Alternative / Contextual Signals (Milestone 4)**

Implements PRD §4.3 (insider conviction, narrative velocity), §8
(EDGAR, Reddit/Stocktwits, MarineTraffic). Issues to be defined in #24.

  ---------------------------------------------------------------------------
  **Issue**   **Title**                               **PRD Section**
  ----------- --------------------------------------- -----------------------
  #24         Phase 3 planning: define issues         §4.3, §8 Insider/
                                                      Shipping/Narrative,
                                                      §10 Phase 3
  ---------------------------------------------------------------------------

**12.6 Phase 4 — Optional Enhancements (Milestone 5)**

Implements PRD §3.3 (out-of-scope, deferred). Issues to be defined
in #25.

  ---------------------------------------------------------------------------
  **Issue**   **Title**                               **PRD Section**
  ----------- --------------------------------------- -----------------------
  #25         Phase 4 planning: define issues         §3.3, §10 Phase 4
  ---------------------------------------------------------------------------

**12.7 Coverage Gaps**

Requirements in the PRD with no implementation issue:

  ---------------------------------------------------------------------------
  **Gap**                    **PRD Section**   **Recommended Action**
  -------------------------- ----------------- ------------------------------
  Futures curve steepness    §4.3              Add Phase 1 issue or
  signal — no Phase 1 issue                    explicitly defer to Phase 2
                                               with a note in Issue #15

  Event detection phase in   §4.2, §10         Add explicit note to Issue
  Phase 1 pipeline — events                    #15 AC: pass events=[] in
  parameter has no source                      Phase 1 run_pipeline()

  TimescaleDB migration       §6.2             No migration plan issue
  path documentation —                         exists. Add before Phase 2
  required before Phase 2                      closes.
  ---------------------------------------------------------------------------
