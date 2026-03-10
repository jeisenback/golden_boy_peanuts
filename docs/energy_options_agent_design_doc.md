**Energy Options Opportunity Agent**

System Design Document

Version 1.0 • March 2026

**1. Overview**

The Energy Options Opportunity Agent is an autonomous, modular system
that identifies options trading opportunities driven by oil market
instability. It ingests market data, supply signals, news events, and
alternative datasets to produce structured, ranked candidate options
strategies.

Designed for an individual contributor with an emphasis on low-cost,
low-overhead feeds, the system surfaces volatility mispricing in
oil-related instruments, ranks candidates by a computed edge score, and
maintains full explainability of all recommendations.

**2. Objectives**

-   Detect volatility mispricing in oil-related instruments.

-   Rank candidate options structures by a computed edge score.

-   Maintain explainability of all recommendations.

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

**4. System Architecture**

The system is composed of four loosely coupled agents that communicate
via a shared market state object and a derived features store. Each
agent can be deployed and updated independently, enabling incremental
enhancement without pipeline disruption.

  ------------------------------------------------------------------------
  **Agent**       **Role**         **Responsibilities**
  --------------- ---------------- ---------------------------------------
  **Data          Fetch &          Pulls crude prices, ETF/equity data,
  Ingestion       Normalize        and options chains; converts disparate
  Agent**                          feeds into a unified market state
                                   object; stores historical data for
                                   volatility and curve calculations.

  **Event         Supply & Geo     Monitors news and geopolitical feeds;
  Detection       Signals          identifies supply disruptions, refinery
  Agent**                          outages, and tanker chokepoints;
                                   assigns confidence/intensity scores to
                                   each detected event.

  **Feature       Derived Signal   Computes volatility gaps (realized vs.
  Generation      Computation      implied), futures curve steepness,
  Agent**                          sector dispersion, insider conviction
                                   scores, narrative velocity, and supply
                                   shock probabilities.

  **Strategy      Opportunity      Evaluates eligible option structures
  Evaluation      Ranking          based on computed signals; generates
  Agent**                          ranked opportunities with edge scores;
                                   includes references to contributing
                                   signals for explainability.
  ------------------------------------------------------------------------

Data flows unidirectionally: raw feeds are ingested and normalized,
events are detected and scored, features are derived, and strategies are
evaluated and ranked. Output is written to a JSON-compatible structure
for downstream consumption.

**5. Functional Requirements**

**5.1 Data Ingestion & Normalization**

-   Fetch and normalize crude prices, ETFs, energy equities, and options
    chains.

-   Convert disparate feeds into a unified market state object.

-   Store historical data for volatility and curve calculations.

**5.2 Event Detection**

-   Identify supply disruptions, refinery outages, tanker chokepoints,
    and geopolitical events.

-   Assign confidence and intensity scores to each detected event.

**5.3 Feature Generation**

Compute the following derived signals:

-   Volatility gaps (realized vs. implied)

-   Futures curve steepness

-   Sector dispersion

-   Insider conviction scores

-   Narrative velocity / headline acceleration

-   Supply shock probability

**5.4 Strategy Generation**

-   Evaluate eligible option structures based on computed signals.

-   Generate ranked opportunities with an edge score.

-   Include references to contributing signals for explainability.

**5.5 Output**

-   Structured output per candidate: instrument, option structure,
    expiration, edge score, contributing signals.

-   Dashboard or JSON-compatible format suitable for thinkorswim or
    other visualization tools.

**6. Non-Functional Requirements**

-   **Tolerate delayed or missing data without pipeline
    failure.**Resilience:

-   **Market data refreshed on a minutes-level cadence; slower feeds
    (EIA, EDGAR) on daily/weekly schedules.**Latency:

-   **Persist historical raw and derived data for 6--12 months to
    support backtesting.**Retention:

-   **Agents for data ingestion, feature generation, event detection,
    and strategy evaluation are independently deployable.**Modularity:

-   **Lightweight footprint; runnable on local hardware or low-cost
    cloud infrastructure (e.g., a single VM or container).**Deployment:

**7. Data Sources**

All data sources are free or low-cost to minimize operational overhead.
The table below summarizes each layer, source, cost, update frequency,
and the data it provides.

  ---------------------------------------------------------------------------------------------------
  **Layer**             **Source**      **Cost**       **Frequency**   **Notes**
  --------------------- --------------- -------------- --------------- ------------------------------
  Crude Prices          Alpha Vantage / Free           Minutes         WTI, Brent spot/futures
                        MetalpriceAPI                                  

  ETF/Equity Prices     Yahoo Finance / Free           Minutes         USO, XLE, Exxon, Chevron
                        yfinance                                       

  Options Data          Yahoo Finance / Free/Limited   Daily           Strike, expiry, IV, volume
                        Polygon.io                                     

  Supply/Inventory      EIA API         Free           Weekly          Inventories, refinery
                                                                       utilization

  News & Geo Events     GDELT / NewsAPI Free           Cont. / Daily   Energy disruptions, sanctions

  Insider Activity      SEC EDGAR /     Free/Limited   Daily           Executive trades
                        Quiver Quant                                   

  Shipping/Logistics    MarineTraffic / Free tier      Continuous      Tanker flows
                        VesselFinder                                   

  Narrative/Sentiment   Reddit /        Free           Continuous      Retail / news sentiment
                        Stocktwits                                     velocity
  ---------------------------------------------------------------------------------------------------

**8. Output Schema**

Each strategy candidate is emitted as a structured object with the
following fields:

  -------------------------------------------------------------------------
  **Field**          **Type**         **Description**
  ------------------ ---------------- -------------------------------------
  **instrument**     string           Target instrument, e.g. USO, XLE,
                                      CL=F (WTI)

  **structure**      enum             Options structure: long_straddle \|
                                      call_spread \| put_spread \|
                                      calendar_spread

  **expiration**     integer (days)   Target expiration in calendar days
                                      from evaluation date

  **edge_score**     float            Composite opportunity score; higher =
                     \[0.0--1.0\]     stronger signal confluence

  **signals**        object           Contributing signal map, e.g. {
                                      tanker_disruption_index: high,
                                      volatility_gap: positive,
                                      narrative_velocity: rising }

  **generated_at**   ISO 8601         UTC timestamp of candidate generation
                     datetime         
  -------------------------------------------------------------------------

Example candidate:

> { \"instrument\": \"USO\", \"structure\": \"long_straddle\",
> \"expiration\": 30,
>
> \"edge_score\": 0.47, \"signals\": { \"tanker_disruption_index\":
> \"high\",
>
> \"volatility_gap\": \"positive\", \"narrative_velocity\": \"rising\" }
> }

**9. MVP Phasing**

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

  **Phase 2** **Supply & Event    Add EIA inventory and refinery
              Augmentation**      utilization; event detection via
                                  GDELT/NewsAPI; compute supply disruption
                                  indices; include event-driven scoring in
                                  edge computation.

  **Phase 3** **Alternative /     Insider trades (EDGAR/Quiver); narrative
              Contextual          velocity (Reddit/Stocktwits); shipping
              Signals**           data (MarineTraffic); cross-sector
                                  correlation agent; edge scoring
                                  incorporates all layers.

  **Phase 4** **Optional /        OPIS or regional refined pricing (paid);
              High-Fidelity       exotic/multi-legged option structures;
              Enhancements**      automated execution integration.
  --------------------------------------------------------------------------

**10. Operational Requirements**

-   Lightweight local or cloud deployment (single VM or container
    target).

-   Historical data storage sized for backtesting (6--12 months
    minimum).

-   Scoring functions kept simple for initial MVP; complexity added
    iteratively.

-   Output compatible with thinkorswim platform or any JSON-capable
    dashboard.

-   No automated trade execution in MVP; system is advisory only.

**11. Future Considerations**

The following enhancements are explicitly deferred but architecturally
anticipated:

-   OPIS or regional refined product pricing for more granular supply
    signal fidelity.

-   Exotic and multi-legged option structures (iron condors,
    butterflies, ratio spreads).

-   Automated execution integration via broker API (e.g., TD Ameritrade
    / Schwab API).

-   Backtesting harness to validate edge score predictiveness against
    historical outcomes.

-   ML-based signal weighting to replace static edge score heuristics
    over time.
