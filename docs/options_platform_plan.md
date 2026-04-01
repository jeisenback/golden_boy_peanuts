# Options Platform Plan

**Energy Options Opportunity Agent — Platform Roadmap**

Version 1.0 · April 2026

---

## 1. Current State Review (Phase 1 + Phase 2 — v0.2.0)

### 1.1 What Has Been Built

The system at v0.2.0 is a fully functioning **signal pipeline** that identifies candidate options
strategies driven by energy market data. The four-agent architecture is complete:

| Agent | Status | Key Outputs |
|-------|--------|-------------|
| **Ingestion** | ✅ Complete | `MarketState`: WTI, Brent, USO, XLE, XOM, CVX prices + options chains |
| **Event Detection** | ✅ Complete | `DetectedEvent` list from GDELT/NewsAPI/EIA, LLM-classified |
| **Feature Generation** | ✅ Complete | `FeatureSet`: vol gaps, sector dispersion, futures curve steepness, supply shock probability |
| **Strategy Evaluation** | ✅ Complete | `StrategyCandidate` list ranked by composite edge score |

**Pipeline flow:**
```
run_ingestion() → run_event_detection() → run_feature_generation() → evaluate_strategies()
```

**Data storage:** PostgreSQL 15+ with six tables:
`market_prices`, `options_chain`, `feature_sets`, `strategy_candidates`,
`eia_inventory`, `detected_events`

**Edge scoring formula (Phase 2):**
```
base  = vol_gap_norm × 0.70 + sector_dispersion × 0.30
score = base × (1 + 0.30 × supply_shock_prob) × (1 + 0.15 × |curve_steepness|)
result = min(score, 1.0)
```

**Test coverage:** 280 passing unit tests, 15 integration tests, 93%+ coverage on ingestion,
0 bandit HIGH findings.

### 1.2 What the Pipeline Produces Today

For each evaluation cycle the pipeline outputs a list of `StrategyCandidate` objects like:

```json
{
  "instrument": "CL=F",
  "structure": "long_straddle",
  "expiration": 30,
  "edge_score": 0.683,
  "signals": {
    "volatility_gap": "positive",
    "sector_dispersion": "medium",
    "supply_shock_probability": "high",
    "futures_curve_steepness": "backwardation"
  },
  "generated_at": "2026-03-19T14:30:00Z"
}
```

### 1.3 What Is Missing for a Complete Options Platform

The signal pipeline is the engine. An **options platform** needs:

| Layer | Status | Description |
|-------|--------|-------------|
| BSM Greeks engine | ✅ Added (this PR) | Delta, gamma, theta, vega, rho per candidate |
| Liquidity filter | ✅ Added (this PR) | Min volume/OI check on ATM option |
| Alternative signals (Phase 3) | ❌ Not started | Insider conviction, narrative velocity, shipping data |
| Backtesting harness | ❌ Prototype only | Full P&L validation of edge scores vs. outcomes |
| Scheduler / automation | ❌ Not started | Cron-driven pipeline with alerting |
| Output / export layer | ❌ Not started | thinkorswim import format, JSON/CSV export |
| CLI interface | ❌ Not started | `python -m src run` single-command pipeline |
| Risk / position tracking | ❌ Not started | Paper portfolio with Greeks aggregation |
| Web dashboard | ❌ Out of scope (Phase 4+) | Visual UI for recommendations |
| ML-based scoring | ❌ Out of scope (Phase 4+) | Replace heuristic weights with learned weights |

---

## 2. Platform Vision

The target state is a **self-contained, locally runnable options intelligence platform** that:

1. **Ingests** live market data on a scheduled cadence (every 15 minutes during trading hours).
2. **Detects** energy market events in near-real-time via GDELT, NewsAPI, and EIA.
3. **Scores** candidate strategies with a composite edge signal incorporating volatility,
   event, and alternative signals.
4. **Prices** each candidate with BSM Greeks (delta, gamma, theta, vega, rho).
5. **Filters** illiquid options before surfacing candidates.
6. **Exports** results in thinkorswim-compatible JSON for direct import.
7. **Tracks** paper positions and reports Greeks-adjusted P&L.
8. **Validates** edge score predictiveness via a backtesting harness.

The platform is advisory only. No automated trade execution.

---

## 3. Phase 3 — Alternative Signals (Sprint 9–10)

**Goal:** Add three additional signal layers to the feature set: insider conviction,
narrative velocity, and tanker/shipping disruption index. These are the highest-ROI
signals for energy options — EDGAR filings and Reddit/Stocktwits sentiment are free
and directly correlated with IV spikes.

### 3.1 Insider Conviction Score (`compute_insider_conviction`)

**Signal:** Score based on executive option purchases/sales reported to SEC EDGAR.
Large insider buys ahead of earnings or supply announcements often precede IV
expansion.

**Data source:** SEC EDGAR EFTS full-text search API (free) or Quiver Quant (free tier).

**Formula:**
```
insider_score = Σ (trade_size_usd / normalizer) × direction_weight × recency_decay
```
where `direction_weight` = +1.0 for buys, −1.0 for sells, and `recency_decay`
exponentially discounts trades older than 30 days.

**Output:** `FeatureSet.insider_conviction_score` in [0.0, 1.0].

**Issues to create:**
- `#N` Fetch EDGAR insider trades — EDGAR EFTS API, XOM/CVX in-scope
- `#N+1` Implement `compute_insider_conviction()` — recency-weighted buy/sell score
- `#N+2` Integrate insider score into edge scoring multiplier

### 3.2 Narrative Velocity (`compute_narrative_velocity`)

**Signal:** Rate of change in headline count for energy-related topics over a
rolling 24-hour vs. 7-day window. Rising velocity precedes realized volatility
increases (validated by the existing GDELT backtest).

**Data source:** GDELT Doc API v2 (already integrated in Event Detection Agent).

**Formula:**
```
velocity = (headline_count_24h / avg_headline_count_7d) - 1.0
```
Positive = accelerating narrative; negative = cooling off.

**Output:** `FeatureSet.narrative_velocity` ≥ 0.0.

**Issues to create:**
- `#N+3` Implement `compute_narrative_velocity()` — rolling GDELT headline ratio
- `#N+4` Integrate narrative velocity into edge scoring multiplier

### 3.3 Tanker / Shipping Disruption Index (`compute_shipping_disruption`)

**Signal:** Proxy for tanker chokepoint disruptions via MarineTraffic or
VesselFinder free tier. A spike in delayed or re-routed VLCC tankers near Strait
of Hormuz or Bab-el-Mandeb correlates with Brent spot spikes.

**Data source:** MarineTraffic free API or AIS-catcher OSS tool.

**Notes:** Free-tier limits are tight. Phase 3 may use a synthetic proxy from
GDELT tanker-related headlines instead, with AIS integration deferred to Phase 4.

**Issues to create:**
- `#N+5` Research shipping data feasibility — free-tier AIS vs. GDELT proxy
- `#N+6` Implement `compute_shipping_disruption()` — tanker disruption index

### 3.4 Edge Score v3 (Phase 3 formula)

Add the three new signals as multiplicative amplifiers:

```
score_v3 = base_v2
         × (1 + 0.20 × insider_conviction)
         × (1 + 0.15 × narrative_velocity_norm)
         × (1 + 0.10 × shipping_disruption)
```

All multiplier weights are heuristic; Phase 4 will replace them with learned weights
via logistic regression or gradient boosting trained on backtested outcomes.

---

## 4. Phase 3 — BSM Greeks & Liquidity (Added in This PR)

The `src/core/bsm.py` module (added in this PR) provides:

### 4.1 `compute_bsm_greeks(spot, strike, tte_years, iv, option_type, r)`

Returns a `BSMGreeks` dataclass:
```python
@dataclass(frozen=True)
class BSMGreeks:
    delta: float   # position sensitivity to ±$1 underlying move
    gamma: float   # rate of change of delta
    theta: float   # daily time decay (negative for long options)
    vega:  float   # sensitivity per 1-point IV move
    rho:   float   # sensitivity per 1-point rate move
    price: float   # theoretical premium
    option_type: str
```

**No scipy dependency** — uses `math.erf` for the normal CDF.

### 4.2 `greeks_for_strategy(spot, strike_atm, tte_years, iv, structure)`

Computes net Greeks for a multi-leg structure:
- `long_straddle` — long ATM call + long ATM put
- `call_spread` — long ATM call + short OTM call (5% above spot)
- `put_spread` — long ATM put + short OTM put (5% below spot)
- `calendar_spread` — returns `None` (not yet implemented)

### 4.3 Integration with `evaluate_strategies`

When `market_state` is passed to `evaluate_strategies(feature_set, market_state=...)`:

1. **ATM option lookup:** finds the nearest-expiry, closest-strike option for each instrument.
2. **Liquidity filter:** skips options with `volume < 10` or `open_interest < 50`.
3. **BSM computation:** calls `greeks_for_strategy()` and attaches result to `candidate.greeks`.
4. **Signal enrichment:** adds `"liquidity_ok": "true"/"false"` to the candidate's `signals` dict.

Candidates with no live market data still work — `candidate.greeks` is `None` and
`liquidity_ok` is absent from `signals`. Backward compatible.

---

## 5. Phase 3 — Backtesting Harness (Sprint 10)

### 5.1 Current State

The `backtests/backtest_gdelt_vol.py` script validates one hypothesis: GDELT headline
volume spikes predict realized volatility increases. It is a standalone prototype, not
integrated with the live pipeline.

**Limitation:** The backtest does not validate the **edge score** as a predictor of
profitable option trades. It validates only one signal layer.

### 5.2 Proposed Backtesting Architecture

A proper backtesting harness needs to:

1. **Replay historical pipeline runs** using stored `strategy_candidates` and
   `market_prices` / `options_chain` data.
2. **Simulate P&L** for each candidate by computing terminal option value at
   expiry (or a fixed hold period) from historical price data.
3. **Measure predictiveness** of edge score: do higher edge-score candidates
   produce higher returns?
4. **Output Sharpe ratio, win rate, and average return** per structure and
   edge score decile.

**New module:** `src/backtesting/backtest_harness.py`

```python
def run_backtest(
    start_date: datetime,
    end_date: datetime,
    engine: Engine,
) -> BacktestResults:
    """
    Replay strategy candidates from DB and compute P&L against historical prices.
    """
```

**Issues to create:**
- `#N+7` Design backtest schema: `backtest_runs` and `backtest_positions` tables
- `#N+8` Implement `BacktestHarness.run()` — replay candidates, compute terminal value
- `#N+9` Add backtest CLI: `python -m src backtest --start 2026-01-01 --end 2026-03-31`
- `#N+10` QA: backtest vs. known historical IV events (March 2020 oil crash as reference)

---

## 6. Phase 4 — Platform Layer (Sprint 11–12)

Phase 4 turns the pipeline into an interactive platform with scheduling,
export, and paper trading.

### 6.1 Scheduler / Automation

**Goal:** Run the pipeline automatically every 15 minutes during US equity market
hours (09:30–16:00 ET, Mon–Fri).

**Implementation options:**
- **APScheduler** (Python, no cron setup) — preferred for simplicity
- **Cron** (system-level) — viable for single-user deployment
- **GitHub Actions scheduled workflow** — for cloud deployment

**New module:** `src/scheduler.py`

```python
def start_scheduler(interval_minutes: int = 15) -> None:
    """Start the APScheduler background scheduler for pipeline runs."""
```

**Issues to create:**
- `#N+11` Add `src/scheduler.py` with APScheduler integration
- `#N+12` Add `scripts/run_pipeline.sh` — wrapper with logging to `logs/pipeline.log`

### 6.2 CLI Interface

A single-command interface to run the pipeline, backtest, or export results.

**Target UX:**
```bash
python -m src run               # one full pipeline cycle
python -m src run --watch       # continuous mode (uses scheduler)
python -m src backtest          # run backtesting harness
python -m src export --format tos  # export to thinkorswim format
python -m src status            # show last pipeline run and top candidates
```

**New module:** `src/__main__.py`

**Issues to create:**
- `#N+13` Implement `src/__main__.py` CLI with argparse
- `#N+14` Implement `--format tos` export: thinkorswim watchlist CSV format

### 6.3 Output / Export Layer

thinkorswim (TD Ameritrade / Schwab) accepts watchlist imports in a specific CSV format.
The export layer maps `StrategyCandidate` objects to TOS format rows.

**TOS watchlist CSV format:**
```
Symbol,Type,Strike,Expiry,Edge Score,Delta,Vega,Theta
USO,LONG_STRADDLE,40.0,2026-05-16,0.72,0.05,0.45,-0.08
```

**New module:** `src/exporters/tos_exporter.py`

**Issues to create:**
- `#N+15` Implement `src/exporters/tos_exporter.py` — TOS watchlist CSV export
- `#N+16` Add `src/exporters/json_exporter.py` — flat JSON export for dashboards

### 6.4 Paper Portfolio / Position Tracking

Track hypothetical positions opened on pipeline recommendations to measure
real-world edge score performance.

**Schema additions (`db/schema.sql`):**
```sql
CREATE TABLE IF NOT EXISTS paper_positions (
    id              BIGSERIAL   PRIMARY KEY,
    instrument      TEXT        NOT NULL,
    structure       TEXT        NOT NULL,
    strike          NUMERIC     NOT NULL,
    expiration_date TIMESTAMPTZ NOT NULL,
    entry_price     NUMERIC     NOT NULL,
    entry_edge_score NUMERIC    NOT NULL,
    opened_at       TIMESTAMPTZ NOT NULL,
    closed_at       TIMESTAMPTZ,
    exit_price      NUMERIC,
    pnl             NUMERIC,
    status          TEXT        NOT NULL DEFAULT 'open'
);
```

**Issues to create:**
- `#N+17` Add `paper_positions` table and `src/agents/paper_trading/` module
- `#N+18` Implement `open_position()`, `close_position()`, `get_open_positions()`
- `#N+19` Implement `compute_portfolio_greeks()` — aggregate delta/gamma/vega exposure

### 6.5 Alerting

Notify the user when a high-confidence opportunity emerges.

**Channels:**
- Email via SMTP (simple, no external service)
- Pushover or ntfy.sh (free tier push notifications)
- Slack webhook (if team-deployed)

**Trigger:** `edge_score >= 0.65 AND liquidity_ok = true`

**Issues to create:**
- `#N+20` Add `src/alerting/` module with SMTP + ntfy.sh backends
- `#N+21` Integrate alerting into `run_pipeline()` — fire alert on high-score candidates

---

## 7. Phase 5 — ML-Based Scoring (Sprint 13+, Deferred)

Replace static heuristic weights with learned weights trained on backtested outcomes.

### 7.1 Proposed Approach

1. **Feature matrix:** For each historical candidate, extract:
   - vol_gap, sector_dispersion, supply_shock_probability, futures_curve_steepness
   - insider_conviction, narrative_velocity, shipping_disruption
   - BSM Greeks at entry: delta, vega, theta
   - Days-to-expiry, moneyness (spot/strike), ATM IV level

2. **Labels:** Binary outcome — did the trade reach +10% P&L before -10% stop loss?

3. **Model:** Logistic regression (interpretable, no overfitting risk at small sample sizes)
   or gradient boosting (XGBoost) once >500 historical trades are available.

4. **Integration:** Replace `_VOL_GAP_WEIGHT`, `_DISPERSION_WEIGHT`, etc. with model
   predict_proba output. Preserve heuristic formula as a fallback when model is absent.

**Issues to create (when Phase 4 produces sufficient data):**
- `#N+22` Phase 5 planning: define ML training dataset schema
- `#N+23` Implement `src/scoring/ml_scorer.py` — sklearn logistic regression edge scorer
- `#N+24` Add cross-validation harness and backtested AUC reporting

---

## 8. Sprint Roadmap Summary

| Sprint | Theme | Key Deliverables |
|--------|-------|-----------------|
| **Sprint 9** | Phase 3 Alternative Signals | Insider conviction, narrative velocity, compute_shipping_disruption stub |
| **Sprint 10** | Phase 3 Backtesting + Edge v3 | BacktestHarness, edge score v3 formula, alternative signal weights |
| **Sprint 11** | Phase 4 Platform Infra | Scheduler, CLI (`src/__main__.py`), TOS exporter |
| **Sprint 12** | Phase 4 Paper Trading + Alerting | paper_positions table, portfolio Greeks, SMTP/ntfy alerting |
| **Sprint 13+** | Phase 5 ML Scoring | ML scorer (deferred until sufficient backtested data) |

---

## 9. Technical Debt and Pre-Phase-3 Fixes

Before starting Phase 3, the following pre-existing items should be addressed:

| Item | Priority | Notes |
|------|----------|-------|
| `src/core/bsm.py` integration tests | Medium | BSM unit tests added in this PR; integration test against live options chain deferred |
| TimescaleDB migration | Low | db/migrate_timescaledb.sql exists; trigger criteria not yet met (< 6 months data) |
| `compute_insider_conviction` field in FeatureSet | Low | Field exists (None-able) but compute function not yet implemented |
| `narrative_velocity` field in FeatureSet | Low | Field exists (None-able) but compute function not yet implemented |
| Futures curve steepness — live 2nd-month ticker | Medium | `_resolve_second_month_ticker()` works but relies on yfinance probe loop |
| Options chain depth | Medium | Currently fetches nearest 2 expiries; Phase 3 BSM accuracy improves with 4–6 expiries |

---

## 10. Architecture Decision Records (ADRs)

### ADR-001: BSM Without scipy

**Decision:** Implement BSM Greeks using only `math.erf` (Python stdlib).

**Rationale:** scipy adds ~30 MB to the dependency footprint and requires compilation in
some environments. The BSM formula requires only the normal CDF, which is computed exactly
via `erf`. No accuracy loss for standard European option pricing.

**Consequence:** `scipy.stats.norm` not needed at runtime. scipy remains permitted in
backtesting scripts where its statistical functions provide additional value.

### ADR-002: BSM Greeks Are Additive to StrategyCandidate

**Decision:** Attach `BSMGreeks` as an optional field on `StrategyCandidate` rather than
as a separate table join.

**Rationale:** Greeks are computed at evaluation time, not persisted. The `strategy_candidates`
table stores the scored candidate; Greeks are ephemeral and should be recomputed from live IV.
Persisting Greeks would create stale data issues as IV changes between cycles.

**Consequence:** `StrategyCandidate.greeks` is `None` when `market_state` is not provided
(e.g., in replay/backtest mode). Consumers must handle `None`.

### ADR-003: Liquidity Filter Thresholds

**Decision:** `MIN_OPTION_VOLUME = 10`, `MIN_OPTION_OPEN_INTEREST = 50`.

**Rationale:** These are the minimum practical thresholds for energy sector options on
USO/XLE/XOM/CVX. Options below these thresholds have wide bid-ask spreads that would
consume the entire edge score premium. Configurable via constants in
`strategy_evaluation_agent.py`.

**Consequence:** During early-morning or pre-market hours, many options may be flagged
`liquidity_ok=false`. Pipeline still returns candidates — liquidity is advisory, not a hard
filter on edge score ranking.

---

## 11. Open Questions for Human Lead

1. **Phase 3 alternative signals priority:** Which signal layer (insider conviction,
   narrative velocity, or shipping disruption) should be built first? Narrative velocity
   reuses existing GDELT infrastructure — lowest friction. Insider conviction requires
   EDGAR API integration.

2. **Alerting channel:** Email (zero dependencies) or ntfy.sh (push to mobile)?
   Both are free and no-setup-required.

3. **Backtesting P&L simulation:** Should terminal value use Black-Scholes theoretical
   exit, or mark-to-market from historical options chain data? Historical options data
   for 6+ months is not yet in the DB.

4. **Calendar spread implementation:** Phase 1 deferred this structure. Phase 3 is the
   right time to add it — requires two expiry dates and a BSM-based roll-down model.
   Human lead to confirm scope.

5. **Sprint 9 start:** Is Sprint 5 (current — HEARTBEAT Sprint 4) fully closed before
   Phase 3 work begins? If Sprint 4 QA issues (#16, #19) are still open, Phase 3 is blocked.
