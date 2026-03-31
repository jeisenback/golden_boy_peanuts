# Feature Analysis: EconomiaUNMSM/OptionStrat-AI

**Date:** 2026-03-31  
**Author:** Copilot (analysis for issue: "analyse this repo for features we could use")  
**Reference:** https://github.com/EconomiaUNMSM/OptionStrat-AI

---

## 1. What Is OptionStrat-AI?

OptionStrat-AI is a derivatives simulation platform for **American-style stock options**
(generic tickers: AAPL, SPY, TSLA, etc.) with a FastAPI backend, React 18 frontend, and
OpenAI-driven portfolio analysis. It has five core subsystems:

| Subsystem | Technology | Purpose |
|-----------|-----------|---------|
| Option Builder (T-Quote) | yfinance / YahooQuery | Live chain extraction: bid, ask, strike, IV, volume, OI |
| Dynamic Risk Heatmap | SciPy BSM engine | P&L matrix: price × DTE with volatility-shock slider |
| AI Portfolio Analyst | LiteLLM → OpenAI | Greek aggregation, blind-gamma/delta warnings |
| Institutional Sentiment | FinViz + VaderSentiment + 13F | News NLP + insider buy/sell classification |
| Theta Gang Optimizer | SciPy BSM | Strategy builder: Bull Put Spread, Iron Condor, Strangle; PoP filter |

---

## 2. Gap Analysis vs Our Project

Our **Energy Options Opportunity Agent** is a 4-agent AI pipeline
(Ingestion → Event Detection → Feature Generation → Strategy Evaluation).
It outputs ranked `StrategyCandidate` objects with a composite `edge_score`
but currently lacks:

| OptionStrat-AI Feature | Our Gap | Priority |
|------------------------|---------|----------|
| BSM Greeks (Δ, Γ, ν, Θ, ρ) | Candidates have `edge_score` but no Greeks for thinkorswim export | **High** |
| Liquidity filter (vol ≥ 10, OI ≥ 50) | We never check whether the ATM option is actually tradeable | **High** |
| Institutional sentiment (insider 13F) | `insider_conviction_score` in FeatureSet is `None` — Phase 3 placeholder | Medium |
| News NLP (VaderSentiment) | `narrative_velocity` in FeatureSet is `None` — Phase 3 placeholder | Medium |
| P&L simulation heatmap | No P&L projection across price scenarios | Low (Phase 4) |
| Broker execution (IBKR/Alpaca) | Out of scope (PRD §3.3) | Out of scope |

---

## 3. Features Adopted in This PR

### 3.1 BSM Greeks Engine (`src/core/bsm.py`)

A pure-Python Black-Scholes-Merton engine using only `math.erfc` for the
normal CDF (no scipy dependency). Provides:

- `compute_bsm_greeks()` — Price + Delta, Gamma, Vega, Theta, Rho for a
  single European call or put.  
- `greeks_for_strategy()` — Combined Greeks for a multi-leg structure
  (`long_straddle`, `call_spread`, `put_spread`).

Greek conventions match thinkorswim / broker display units:
- Vega and Rho are per **1% move** (divided by 100).
- Theta is **per calendar day** (divided by 365).

### 3.2 Liquidity Filter in `evaluate_strategies()`

Mirrors OptionStrat-AI's "zombie option" guard:

```python
MIN_OPTION_VOLUME:        int = 10   # contracts traded today
MIN_OPTION_OPEN_INTEREST: int = 50   # total outstanding contracts
```

Candidates now carry a `liquidity_ok: bool | None` field. The flag is
`None` when `market_state` is not available (Phase 1 compatibility) and
`True`/`False` when the ATM option is checked against both thresholds.

### 3.3 Greeks Enrichment on `StrategyCandidate`

`StrategyCandidate` now accepts optional fields:

| Field | Type | Description |
|-------|------|-------------|
| `greeks` | `dict[str, float] \| None` | BSM Greeks for ATM leg(s) |
| `atm_strike` | `float \| None` | Strike used for Greeks computation |
| `liquidity_ok` | `bool \| None` | Passes min volume + OI thresholds |

These are populated by passing the `MarketState` to `evaluate_strategies()`:

```python
# Pipeline (src/pipeline.py)
candidates = evaluate_strategies(feature_set, market_state=market_state)
```

Backward-compatible: omitting `market_state` returns candidates with
`greeks=None`, `atm_strike=None`, `liquidity_ok=None`.

---

## 4. Features Deferred to Future Phases

### Phase 3 (already planned)

| Feature | From OptionStrat-AI | Our Phase 3 Issue |
|---------|---------------------|-------------------|
| News sentiment NLP | VaderSentiment over FinViz feeds | #24 narrative_velocity |
| Insider conviction | 13F via YahooQuery | #24 insider_conviction_score |

**Recommendation:** When Phase 3 implements `narrative_velocity` and
`insider_conviction_score`, adopt VaderSentiment (MIT license) for the
news layer — zero runtime cost, solid accuracy for financial headlines.
The `compute_supply_shock_probability()` function can be extended to
incorporate sentiment weights alongside its current event-type × intensity model.

### Phase 4 (optional)

| Feature | From OptionStrat-AI | Rationale |
|---------|---------------------|-----------|
| P&L heatmap | BSM price × DTE matrix | Useful for UI; overkill for pipeline output |
| Iron Condor / Strangle | Theta Gang optimizer | Add to `OptionStructure` enum when user demand exists |
| Monte Carlo simulation | Listed in OptionStrat-AI roadmap | Phase 4 backtesting scope |

---

## 5. Expanded Project Goal Statement

**Before:** _Identify options trading opportunities driven by oil market instability._

**After:** _Identify, quantify, and characterize actionable options opportunities in oil-related
instruments by combining energy-specific signals (supply shocks, futures curve, event detection)
with standard option risk parameters (BSM Greeks, liquidity), producing ranked candidates that
are directly importable into trading platforms such as thinkorswim._

The expansion adds three dimensions to the output:

1. **Quantitative risk parameters** (Greeks) so traders understand the position they are entering.
2. **Liquidity validation** so every candidate is actually executable at market prices.
3. **Platform-ready output** — `greeks` + `atm_strike` + `expiration` aligns exactly with
   thinkorswim's position import format (PRD §4.5).

---

## 6. Architecture Compatibility

OptionStrat-AI uses **FastAPI + React** for interactive simulation; our pipeline is a
**headless batch process**. The two approaches are complementary:

- Our pipeline produces the _signal-driven_ ranked list (energy domain, event-aware).
- OptionStrat-AI's heatmap can be used as a _visualization layer_ on top of our output:
  feed our `StrategyCandidate` objects into its BSM heatmap to simulate P&L.

The shared BSM math (`src/core/bsm.py`) means our output is already in the right units
for any downstream visualization built on the same model.

---

## 7. No New Runtime Dependencies

The BSM implementation uses only `math.erfc` from the Python standard library.
`scipy` is **not** required. This is consistent with our ESOD constraint of a
lightweight footprint.
