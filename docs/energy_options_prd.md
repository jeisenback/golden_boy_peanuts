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
