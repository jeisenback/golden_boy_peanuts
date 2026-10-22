# Edge Research Protocol and Test Queue: Design

**Status:** PROPOSAL for human-lead review. Nothing here is implemented.
**Issue:** #252 (umbrella: queue, variant ledger, stop date)
**Author:** Claude Code session, 2026-10-20
**Decisions already made by the human lead (2026-10-20):**
- The goal is a systematic strategy with a validated edge.
- The account is small and defined-risk only: long stocks and ETFs, and defined-risk option spreads. No shorting, no naked options.
- The data budget is open, behind gates (section 6).
- Direction: a test queue (option A of three offered).

---

## 1. Purpose and success definition

Find, or rule out, a strategy that a one-person, small, defined-risk account can run systematically and that has a validated edge.

A candidate counts as validated only if all of these hold:
- After realistic costs it beats a simple baseline on return per unit of drawdown.
- That holds on data its rules were never tuned on (a holdout period fixed in advance).
- The number of variants tried across the whole search is recorded and reported with the result.
- It survives paper trading with real quotes before any live money.

The energy options pipeline stops being the goal. It becomes one test subject among several (section 7).

## 2. What has been tried

Between 2026-10-09 and 2026-10-20 four decision tests and one post hoc backtest were run on free data. None found an edge.

| Test | Question | Verdict |
|---|---|---|
| #217 / #249 | Does buying volatility pay when the OVX gap is wide? Is energy a special slice for volatility mispricing? | No. Options were priced rich in every market tested; energy sits mid-pack. |
| #240 | Does the futures-curve direction mapping hold? | Contrary evidence; weight set to 0. Post hoc, not pre-registered. |
| #250 | Does S&P 500 option selling (CBOE PUT, WPUT, BXM, CNDR) beat buy-and-hold after removing beta? | No. About zero alpha; mostly equity beta at lower volatility. |
| #251 H1 | Do insider cluster purchases predict abnormal returns at 63 days? | No (net -1.7%, survivor-biased sample, so decisive). |
| #251 T2 | Does the production insider formula separate winners from losers? | Not supported (spread +0.14%). |

The variant ledger starts here with five decision tests and zero GO verdicts. It is maintained in #252.

## 3. Constraints

- **Account:** long stocks and ETFs and defined-risk option spreads only. Any candidate that needs shorting or naked options is out unless it can be expressed within this limit.
- **Budget:** open, but each purchase needs a passed free test or an unavoidable data need, a sample coverage check, and the human lead's explicit yes, within a total cap the lead sets (section 6).
- **Authority:** the human lead owns spending, merging, PRD and ESOD edits, new dependencies, and moving any candidate to the next stage.
- **Honesty about the base rate:** most candidate edges fail. A queue that ends with no GO is a valid outcome.

## 4. The protocol every candidate must pass

### 4.1 The card
Written and committed to the test's issue before any data is pulled. It contains:
- the mechanism: why the edge should exist and persist;
- the data and its known biases;
- the trading expression, within the constraints in section 3;
- the cost model;
- the baseline it must beat;
- frozen go/no-go rules, with numeric thresholds;
- the holdout period, left untouched until the rules are frozen.

The thresholds are set in each card, not in this spec. This spec fixes the structure.

### 4.2 Stages
1. **Stage 0, free proxy test.** Cheap and fast. It can kill an idea or promote it. A pass is never a go.
2. **Stage 1, clean data with costs.** Survivorship-free prices or historical option quotes, the actual structure, and bid/ask costs. Money is spent here, only through the gates in section 6.
3. **Stage 2, paper trading** for 6 to 12 months with real quotes, logging fills against mid prices.
4. **Stage 3, small live size,** only after the first three pass, with a loss limit set beforehand.

### 4.3 Standing rules
- **Pre-registration:** thresholds and parameters are frozen before the data is pulled. Any deviation is recorded in the issue before results are computed, with its direction (whether it favors the signal).
- **One-sided bias:** when the data is biased toward the signal (for example survivor-only prices), only a failure is decisive. A pass is inconclusive until clean data is used.
- **Inference:** confidence intervals cluster by calendar month or by event date, because events cluster in time. Report the effective sample size, not the raw row count.
- **Missing data:** report the number and share of events with no usable data, by year. Never drop them silently.
- **Variant ledger:** every decision test and every variant is counted in #252 and reported with each verdict.
- **Exploratory analysis:** anything run after the verdict is labeled exploratory and cannot change it.
- **Baseline first:** no candidate is judged without the Q1 baseline results on the same period.

## 5. The test queue

One candidate is open at a time. Order: cheapest and most informative first.

### Q1. Trend baseline on liquid ETFs
- **Hypothesis:** holding a broad asset only while it is above its own long moving average (for example 10 months), otherwise cash, improves return per unit of drawdown versus buy-and-hold.
- **Why first:** free data; survivorship barely matters for broad ETFs; a long evidence record. It sets the bar every later candidate must clear and is the fallback product if nothing else works.
- **Expression:** shares of ETFs; no options.
- **Unlocks:** the baseline numbers used in every later card.

### Q2. Insider purchases at 6 to 12 months
- **Hypothesis:** purchases by several insiders of the same company (and "opportunistic" purchases) are followed by abnormal returns at long horizons, especially in smaller companies.
- **Why this is not a rescue of H1:** H1 tested 63 days on survivor-biased prices and failed. This is a new pre-registered test at different horizons. The ledger counts it as a second look at the same filings, which raises the bar for believing a pass.
- **Data:** SEC Form 3/4/5 bulk files (free, already downloaded in the working session); prices.
- **Stage 0:** free prices, designed only to kill the idea. If it fails, stop.
- **Stage 1:** survivorship-free prices, bought only after a Stage 0 pass.
- **Expression to settle in the card:** shares, or long-dated defined-risk call spreads.

### Q3. Earnings-event options
- **Hypothesis:** implied earnings moves exceed realized moves by enough to survive costs for defined-risk short-premium structures (iron condors, credit spreads), across thousands of events a year.
- **Data:** historical option quotes with bid/ask and earnings dates. No free proxy exists, so this is a paid test from the start, beginning with a small pilot on a handful of stocks to check data quality.
- **Known risks:** crowded; heavy tails around earnings; costs matter most on small accounts.

## 6. Data and budget gates

A purchase requires all three:
1. a passed free test, or an unavoidable data need (Q3);
2. a coverage check on a sample before paying (history back to 2007 or earlier, delisted names included, personal-use licence);
3. the human lead's explicit yes, within the total cap the lead sets before the first purchase.

Likely data classes: survivorship-free stock prices, and historical option quotes with bid/ask. Vendors are compared with verified prices at the time of the decision, not from memory.

## 7. The energy options pipeline, parked

Parked, not deleted.
- The nightly run keeps running from `main` as it is (curve at weight 0). It costs nothing and lets #238 close once a finite curve shows in a log.
- `_W_INSIDER` should be set to 0 in a small PR, because both insider tests found no support.
- #244 and #245 (insider recentering and the alternative-data feeds) are held off `main` until a test shows they are worth the extra outbound requests and failure modes.
- #246, #247 and #248 (snapshot inputs, Perigon) stay in the backlog.
- The supply-shock signal is the only energy-specific live signal and remains untested because it has no history. It stays out of the queue unless a clean way to test it appears.

## 8. Stop rule

- One candidate at a time. No new idea enters the queue while another is open.
- The search stops when Q1 to Q3 each reach a Stage 1 verdict, or on 2027-01-18 (90 days from 2026-10-20), whichever comes first.
- If there is no GO at that point, the next step is a new brainstorm to choose between: the trend baseline as the product, a research and watch tool, or a pause.
- Total data spend is capped at an amount the human lead sets before the first purchase.

## 9. Artifacts and process

- **Issues:** the umbrella issue #252 holds the queue, ledger and stop date. Each test gets its own issue with the card in the body and the verdict as a comment.
- **Code:** analysis scripts are throwaway by default and are not committed. A shared evaluation helper (clustered bootstrap, matched controls, missing-data reporting) is worth building only once a second test needs identical code; the implementation plan decides when. Nothing is added to `src/` without the lead's approval.
- **Docs:** this spec is a new file and changes no existing document. PRD, ESOD, design doc and SDLC edits remain the lead's.

## 10. Out of scope

A trading system, order execution, alerts, ML weight tuning, new data feeds beyond what a card requires, changes to the PRD or ESOD, and any live trading before Stage 3 is approved.

## 11. Risks and limits

- **Low base rate:** most candidates fail; each additional test also raises the chance of a false find, which is why the ledger exists.
- **Free-data bias:** survivor-only prices flatter signals; this is why free tests can only kill.
- **Small-account costs:** commissions, bid/ask spreads and assignment risk weigh more on small positions.
- **Behavioral risk:** a validated strategy still needs the discipline to follow it through drawdowns; the loss limit in Stage 3 is set in advance for that reason.
- **Model risk:** a pass in one period does not guarantee persistence; Stage 2 paper trading is the check.
- **Taxes and account rules** are not modelled.

## 12. Decisions required from the human lead

1. Approve the protocol and the queue order (Q1, Q2, Q3).
2. Confirm the stop date of 2027-01-18.
3. Set the total data spend cap before the first purchase (it can wait until Q2 passes Stage 0).
4. Approve the small PR setting `_W_INSIDER` to 0, and holding #244 and #245 off `main`.
