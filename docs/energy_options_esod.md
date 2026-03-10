**Engineering Statement of Direction**

Energy Options Opportunity Agent

Version 1.0 • Q1 2026 • Horizon: 0--3 Months

**1. Purpose**

This Engineering Statement of Direction (ESOD) establishes the technical
standards, architectural decisions, and engineering expectations for the
Energy Options Opportunity Agent during its initial 0--3 month build
phase. It is a living reference for the engineering team and product
stakeholders.

This document is directional, not prescriptive. It defines the standards
within which implementation decisions should be made, while leaving room
for pragmatic judgment at the component level.

+-----------------------------------------------------------------------+
| **Scope Note**                                                        |
|                                                                       |
| Agents (LangChain / LangGraph) are used to accelerate software        |
| development and scaffolding. They are not runtime dependencies. The   |
| production system must operate correctly without any agent framework  |
| present at runtime.                                                   |
+-----------------------------------------------------------------------+

**2. Context & Background**

The Energy Options Opportunity Agent identifies options trading
opportunities driven by oil market instability. It ingests market data,
supply signals, news, and alternative datasets to produce ranked,
explainable candidate options strategies across WTI, Brent, USO, XLE,
XOM, and CVX.

The system is currently operated by a single contributor but is designed
for growth: more instruments and data sources, eventual multi-user and
team access, and cloud deployment are all on the horizon. Engineering
decisions must account for this trajectory from day one.

+-----------------------------------------------------------------------+
| **Engineering Principle**                                             |
|                                                                       |
| Build for today, design for tomorrow. MVP simplicity is valued, but   |
| architectural choices that create hard migration walls are explicitly |
| discouraged.                                                          |
+-----------------------------------------------------------------------+

**3. Technical Standards**

The following standards apply to all components built during the 0--3
month horizon unless a documented exception is approved.

  ------------------------------------------------------------------------
  **Area**        **Standard / Choice**  **Rationale**
  --------------- ---------------------- ---------------------------------
  **Language**    **Python 3.11+**       Primary runtime language for all
                                         agents and pipeline components.
                                         Type hints required throughout.

  **Package       **pip +                Reproducible environments across
  Management**    requirements.txt       local and CI contexts.
                  (MVP); Poetry as team  
                  scales**               

  **Agent         **LangChain /          Used to accelerate agent
  Framework**     LangGraph (dev tooling development. Not a runtime
                  only)**                dependency. Agents must function
                                         without LangChain at runtime.

  **LLM           **Provider-agnostic    Allows swap of underlying model
  Interface**     wrapper module**       (OpenAI, Anthropic, local)
                                         without changes to agent code.

  **Data Storage  **PostgreSQL 15+**     MVP baseline. Multi-user and
  --- Phase 1**                          cloud-ready. Schema must be
                                         designed for TimescaleDB
                                         compatibility from day one.

  **Data Storage  **TimescaleDB          Migrate when backtesting volume
  --- Phase 2**   (Postgres extension)** or query latency triggers are
                                         met. Zero SQL re-tooling
                                         required.

  **Local Dev     **SQLite**             Permitted for local unit tests
  Storage**                              and offline dev only. Never used
                                         in staging or production.

  **Config        **Environment          Secrets and API keys must never
  Management**    variables + .env       be committed to source control.
                  (python-dotenv)**      

  **Logging**     **Python logging +     Machine-readable logs required
                  structured JSON logs** for pipeline debugging and future
                                         observability tooling.
  ------------------------------------------------------------------------

**4. Data Storage Direction**

**4.1 Rationale**

Data storage is one of the highest-leverage architectural decisions for
this system. The combination of critical backtesting performance
requirements, a growth trajectory toward multi-user and cloud
deployment, and willingness to manage infrastructure points clearly away
from embedded solutions and toward a managed relational database with a
time-series upgrade path.

**4.2 Option Tradeoffs**

  ----------------------------------------------------------------------------------
  **Option**        **Strengths**            **Weaknesses**      **Verdict**
  ----------------- ------------------------ ------------------- -------------------
  **SQLite**        Zero setup; portable;    Single-writer; poor **Dev/test only**
                    great for local dev      time-series range   
                                             scans; no cloud or  
                                             multi-user path     

  **PostgreSQL**    Battle-tested;           General-purpose;    **MVP baseline**
                    multi-user; cloud-ready; not optimized for   
                    rich ecosystem;          time-series at      
                    TimescaleDB-compatible   scale               

  **TimescaleDB**   Postgres extension;      Slightly more       **Target state**
                    time-series optimized;   setup; requires     
                    fast range queries; same extension           
                    SQL interface; zero      management          
                    re-tooling from Postgres                     

  **InfluxDB**      Purpose-built            Non-SQL query       **Not recommended**
                    time-series; very fast   language; weaker    
                    writes                   relational support; 
                                             harder cloud        
                                             migration path      
  ----------------------------------------------------------------------------------

**4.3 Adopted Direction: PostgreSQL → TimescaleDB**

+-----------------------------------------------------------------------+
| **Decision**                                                          |
|                                                                       |
| Phase 1 (MVP): PostgreSQL 15+. All schema design and query patterns   |
| must be TimescaleDB-compatible from day one.                          |
|                                                                       |
| Phase 2 (Growth): Migrate to TimescaleDB when any of the following    |
| triggers are met:                                                     |
|                                                                       |
| • Historical data exceeds 6 months of tick-level market data          |
|                                                                       |
| • Backtesting range queries consistently exceed 5 seconds             |
|                                                                       |
| • Team size grows beyond a single contributor                         |
|                                                                       |
| SQLite is permitted for local unit testing and offline development    |
| only. Never used in staging or production.                            |
+-----------------------------------------------------------------------+

Because TimescaleDB is a PostgreSQL extension, the migration requires no
SQL re-tooling, no ORM changes, and no data model redesign --- only the
addition of the extension and conversion of relevant tables to
hypertables. This migration path should be planned and documented before
Phase 2 begins.

**5. Agent Tooling & Framework Standards**

**5.1 Role of Agents in This System**

LangChain and LangGraph are adopted as development-time tooling only.
Their role is to accelerate authoring of agent scaffolding, prompt
construction, and pipeline wiring --- not to serve as a runtime
dependency.

+-----------------------------------------------------------------------+
| **Architectural Rule**                                                |
|                                                                       |
| All agents and pipeline components must pass their test suites when   |
| LangChain and LangGraph are not installed. Runtime code must not      |
| import from langchain.\* or langgraph.\* directly. Use abstraction    |
| wrapper modules that isolate this dependency.                         |
+-----------------------------------------------------------------------+

**5.2 Permitted Agent Usage**

-   Code generation and scaffolding during development sprints.

-   Prompt engineering and evaluation harnesses (non-production).

-   LangGraph workflow graphs used as development prototypes, then
    refactored into native Python pipelines before production promotion.

-   Documentation generation and test case drafting.

**5.3 LLM Interface Standard**

All LLM calls must be made through a thin, provider-agnostic wrapper
module. This wrapper must accept a model identifier and return a
normalized response object. Direct instantiation of provider clients
(OpenAI, Anthropic, etc.) in agent or pipeline code is prohibited.

**6. Testing & Validation Standards**

Given external API reliability and team capacity constraints, testing
standards are designed to maximize confidence with minimal overhead.
Automation is prioritized over manual validation at every layer.

  ------------------------------------------------------------------------
  **Layer**       **Tooling**           **Standard**
  --------------- --------------------- ----------------------------------
  **Unit Tests**  **pytest**            All feature generators, edge
                                        scoring functions, and data
                                        normalization logic must have unit
                                        test coverage.

  **Integration   **pytest +            Pipeline integration tests run
  Tests**         testcontainers        against a real Postgres instance
                  (Postgres)**          via Docker. No mocking of the DB
                                        layer.

  **Agent         **Golden dataset      Agent outputs validated against
  Validation**    comparison**          curated market scenarios with
                                        known expected edge scores.

  **API           **tenacity (retry +   All external API calls wrapped
  Reliability**   circuit breaker)**    with exponential backoff. Pipeline
                                        must degrade gracefully on feed
                                        failure.

  **Data          **Pydantic schema     All inbound data validated at
  Quality**       validation**          ingestion boundary. Malformed
                                        records logged and quarantined,
                                        never silently dropped.

  **CI**          **GitHub Actions (or  Tests run on every commit. Merges
                  equivalent)**         to main are blocked on test
                                        failure.
  ------------------------------------------------------------------------

+-----------------------------------------------------------------------+
| **API Reliability Standard**                                          |
|                                                                       |
| All external data source integrations must implement:                 |
|                                                                       |
| • Exponential backoff with jitter via the tenacity library            |
|                                                                       |
| • Configurable timeout per source                                     |
|                                                                       |
| • Last-known-good value caching for critical feeds                    |
|                                                                       |
| • Graceful degraded-mode output when a feed is unavailable            |
|                                                                       |
| A failed feed must never take down the pipeline.                      |
+-----------------------------------------------------------------------+

**7. Risks & Mitigations**

  -----------------------------------------------------------------------------
  **Risk**         **Severity**   **Impact**             **Mitigation**
  ---------------- -------------- ---------------------- ----------------------
  **External API   **High**       Pipeline stalls; stale Retry logic and
  rate limits or                  or missing data leads  circuit breakers
  outages**                       to missed signals or   (tenacity). Cache
                                  bad candidates.        last-known-good
                                                         values. Emit
                                                         degraded-mode output
                                                         rather than fail hard.

  **Feed schema    **Medium**     Silent data corruption Pydantic validation at
  changes (Yahoo,                 or ingestion failure   ingestion boundary.
  GDELT, EIA)**                   if upstream format     Alert immediately on
                                  changes without        validation failures.
                                  notice.                

  **Single         **High**       Bottleneck on feature  Enforce modular agent
  contributor /                   delivery; knowledge    boundaries. Document
  small team**                    concentration; no peer decisions as ADRs.
                                  review by default.     Prioritize ruthlessly
                                                         across MVP phases.

  **LangChain      **Medium**     Increases fragility    Enforce architectural
  becoming a                      and upgrade surface    rule: no langchain.\*
  runtime                         area in production.    imports in production
  dependency**                                           runtime. Validate via
                                                         CI import check.

  **Postgres -\>   **Low**        Delaying too long may  Define migration
  TimescaleDB                     require costly         trigger criteria now.
  migration                       backfill of            Plan migration window
  delay**                         hypertables.           before Phase 2 begins.
  -----------------------------------------------------------------------------

**8. Out of Scope (This Horizon)**

The following are explicitly deferred and should not influence
implementation decisions during the 0--3 month window:

-   Automated trade execution or broker API integration.

-   Exotic or multi-legged options structures (iron condors, ratio
    spreads, etc.).

-   OPIS or regional refined product pricing data.

-   ML-based dynamic signal weighting (static scoring functions only in
    MVP).

-   Multi-user authentication or access control.

-   Cloud deployment infrastructure (local deployment only in Phase 1).

+-----------------------------------------------------------------------+
| **Deferral Note**                                                     |
|                                                                       |
| Deferred items should still inform architecture and schema design to  |
| avoid hard migration barriers. For example, schema design should      |
| accommodate future multi-user tenancy even if not implemented now.    |
+-----------------------------------------------------------------------+

**9. Success Criteria (0--3 Month Horizon)**

At the end of the initial horizon, the following criteria define
engineering success:

1.  All four agent modules (ingestion, event detection, feature
    generation, strategy evaluation) are independently deployable and
    testable.

2.  PostgreSQL schema is designed and documented with TimescaleDB
    migration compatibility confirmed.

3.  All external API integrations include retry logic, circuit breakers,
    and degraded-mode behavior.

4.  Unit and integration test coverage exists for all feature generators
    and edge scoring functions.

5.  No LangChain or LangGraph imports exist in production runtime code
    (enforced via CI).

6.  Phase 1 ranked candidate output is produced and validated against at
    least one golden dataset scenario.

**10. Review & Update Cadence**

This ESOD covers the 0--3 month engineering horizon and should be
reviewed at the following milestones:

-   End of Phase 1 (MVP candidate output working): review storage
    migration trigger criteria.

-   Start of Phase 2 (supply & event augmentation): update agent tooling
    and testing standards as needed.

-   Any change in team size: re-evaluate all standards scoped for a
    single contributor.

Updates to this document require acknowledgment from both engineering
and product stakeholders before taking effect.
