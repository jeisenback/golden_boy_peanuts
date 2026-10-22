# Edge Research Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the first stages of the edge search defined in the spec: park the energy insider weight, then take Q1 (trend baseline) and Q2 (insiders at long horizons) through Stage 0, prepare Q3's data decision, and hold the stop-date review.

**Architecture:** Almost no production code. One small code change (Task 1). Every other task is a research task: a card posted to its own GitHub issue and frozen before data is pulled, a throwaway analysis script in the scratchpad, and a verdict posted as an issue comment. Nothing from the scratchpad is committed.

**Tech Stack:** Python 3.11+, pandas, numpy (already installed), FRED and Yahoo for prices, SEC bulk Form 4 files, pytest for Task 1.

**Spec:** `docs/superpowers/specs/2026-10-20-edge-research-protocol-design.md` (umbrella issue #252)

## Global Constraints

- Account limit: long stocks and ETFs, and defined-risk option spreads only; no shorting, no naked options.
- No new package (even dev-only) and no change to `requirements*.txt`.
- Thresholds are frozen in the card, in the test's issue, before any data is pulled; any later deviation is posted before results are computed, with its direction.
- Free-data tests can only kill a candidate; a pass is never a GO.
- No purchase without all three gates: a passed free test (or unavoidable need), a sample coverage check, and the human lead's explicit yes within the lead's spend cap.
- One candidate open at a time. Stop date: 2027-01-18.
- Merging to `develop` or `main`, PRD/ESOD edits, dependencies and spend belong to the human lead.
- Commits: `<type>(<scope>): <description> (#<issue>)`; end with the attribution lines from the session reminder.

## Review Focus

- **Data gaps hiding in a pass:** Yahoo throttling made 27% of events unresolved in H1. Each run must print missing counts by status and year and abort if unresolved symbols exceed 5% of the universe, not continue silently. (Tasks 3 and 4.)
- **Look-ahead in the trend rule:** a month-end signal traded at that same close would inflate Q1. A deliberately leaked variant must look implausibly good and the lagged variant must be the one reported. (Task 2.)
- **Tests that assume the insider weight:** several existing strategy tests assert maxima that include the 0.15 insider term. They must change in the same commit as the constant. (Task 1.)
- **Scratchpad is lost when the container ends:** the 869 MB of SEC files and cached prices will not survive. Each run posts its input counts and summary tables to the issue so the result stays auditable and the rebuild steps are written down. (Tasks 3 and 4.)
- **A purchase slipping through:** vendor work must stop at a comparison and a sample check; no account creation or payment without the lead's yes. (Task 5.)

## File Structure

- Modify `src/agents/strategy_evaluation/strategy_evaluation_agent.py`: the insider weight constant (Task 1).
- Modify `tests/agents/strategy_evaluation/test_strategy_evaluation_agent.py`: insider tests (Task 1).
- Modify `docs/plans/structure-selection-spec.md`: record the weight change next to the existing amendments (Task 1).
- Scratchpad only (not committed): `q1_trend.py`, `q2_insiders_long.py`, `vendor_notes.md`.

---

### Task 1: Set `_W_INSIDER` to 0

**Files:**
- Modify: `src/agents/strategy_evaluation/strategy_evaluation_agent.py` (the `_W_INSIDER` constant and its comment block)
- Modify: `tests/agents/strategy_evaluation/test_strategy_evaluation_agent.py`
- Modify: `docs/plans/structure-selection-spec.md` (amendment note)

**Interfaces:**
- Produces: `_W_INSIDER: float = 0.0`; a pytest fixture `insider_weighted` that monkeypatches `strategy_evaluation_agent._W_INSIDER` to `0.15` for tests that exercise the mapping.

- [ ] **Step 1: Open an issue** titled "fix(strategy-evaluation): set insider weight to 0, no support in two tests (#251)" with the evidence from #251 and the rule: weight stays 0 until a pre-registered test supports it. Record its number for the commit message.
- [ ] **Step 2: Write the failing tests** in `TestComputeDirectionNet`: `test_insider_has_no_effect_at_the_shipped_weight` (parametrize `score` over `[0.0, 0.5, 2/3, 0.9, 1.0]`; assert `_net("XOM", insider_conviction_score=score) == _net("XOM")`). Run `pytest tests/agents/strategy_evaluation -m "not integration" -q`; expect that one test FAIL.
- [ ] **Step 3: Add the `insider_weighted` fixture** (same pattern as the existing `curve_weighted`) and apply it to every existing test that expects an insider contribution: the insider buying and selling tests, the equal-dollar neutral test, the "all signals maxed" test, the sorted-by-score test and `test_insider_selling_removes_equities_but_not_etfs`. With the fixture applied each keeps its current expected value. Run the same command; expect only the new test FAIL.
- [ ] **Step 4: Change the constant** to `_W_INSIDER: float = 0.0` in `strategy_evaluation_agent.py` and extend the existing comment block with: weight 0 per #251 (cluster purchases net -1.7% at 63 days; production formula spread +0.14%), mapping and recentering kept, do not set a non-zero weight without evidence. Update the `compute_direction_net` docstring range line (practical maximum 0.60).
- [ ] **Step 5: Run** `pytest -m "not integration" -q` and `ruff check src tests`, `black --check src tests`, `mypy src`. Expect all pass. Re-run the two CI-only pipeline scenarios by direct computation if any integration test mentions insider (grep first; expect none).
- [ ] **Step 6: Add one dated amendment line** to `docs/plans/structure-selection-spec.md` (section 3.3, after the #237 note) recording the weight change and linking #251.
- [ ] **Step 7: Commit and open a PR to `develop`** (`fix(strategy-evaluation): set insider weight to 0 until a test supports it (#<issue>)`). Do not merge; the lead merges. Do not release #244 or #245 to `main`.

### Task 2: Q1 trend baseline, Stage 0

**Files:**
- Create (scratchpad, not committed): `q1_trend.py`

**Interfaces:**
- Produces: baseline numbers (CAGR, volatility, Sharpe, maximum drawdown, worst year) on the same ETF universe and period, posted to the Q1 issue; later cards cite them.

- [ ] **Step 1: Open the Q1 issue and post the card** with these proposed values for the lead to confirm or change: universe SPY, EFA, EEM, AGG, GLD, VNQ (common history from 2004-12); signal: hold an ETF next month only if its month-end close is above its 10-month simple average of month-end closes, else the 3-month T-bill; baseline: the same six ETFs equal-weighted, rebalanced monthly; cost: 0.10% of the traded amount per switch; holdout: 2020-01 onward untouched until thresholds are frozen; Stage 0 pass if all of: maximum drawdown <= 0.70 x baseline's, CAGR >= baseline's minus 2.0 percentage points, and both halves (2004-12 to 2014, 2015 to 2026) show lower drawdown than the baseline. **Wait for the lead's reply before freezing.**
- [ ] **Step 2: Write the leak-check first.** In the script, `trend_signal(prices, lag)` returns the monthly hold flag; `lag=0` trades at the same close (leaked), `lag=1` trades the following month (reported). Assert (print and stop if false) that the leaked variant's CAGR exceeds the lagged variant's.
- [ ] **Step 3: Implement the script** (monthly month-end series, flags, costs, metrics, halves, and the equal-weight baseline), run it, and print missing-data counts per ETF.
- [ ] **Step 4: Post the verdict comment** on the Q1 issue (tables, the leak-check result, the pass/fail against each frozen rule, limits). Update the ledger in #252.

### Task 3: Q2 insider purchases at long horizons, Stage 0

**Files:**
- Create (scratchpad, not committed): `q2_insiders_long.py`

**Interfaces:**
- Consumes: the H1 event definition from issue #251 (cluster purchase: at least 2 officers or directors, $50,000, 30 days, filing date, entry at the next close) and the SEC Form 4 bulk files and Yahoo price download method used there.
- Produces: a verdict comment on the Q2 issue.

- [ ] **Step 1: Open the Q2 issue and post the card** with proposed values: same events as H1; horizons 126 and 252 trading days with 252 primary; controls and 1.0% round-trip cost as in H1; Stage 0 pass only if mean net abnormal return at 252 days >= +3.0%, month-clustered bootstrap lower bound > 0, positive in both halves, and unresolved or missing symbols reported by year. Record in the card that this is the second look at these filings, and add both horizons to the ledger in #252. **Wait for the lead's reply before freezing.**
- [ ] **Step 2: Rebuild the inputs** (SEC zips, events, prices) if the scratchpad no longer has them; use a paced download and the per-ticker error classification from the H1 run. Abort with a clear message if unresolved symbols exceed 5% of the universe.
- [ ] **Step 3: Run the analysis** with the frozen rules and post the verdict comment, including the missing-data table by year. Remember: the sample is survivor-biased, so only a NO-GO is decisive.
- [ ] **Step 4: If NO-GO,** mark Q2 closed in #252 and move to Task 4. **If it passes,** do not buy data; post the Stage 1 data need and the cost question to the lead (Task 5 gates).

### Task 4: Data vendor comparison (no purchase)

**Files:**
- Create (scratchpad, not committed): `vendor_notes.md`

- [ ] **Step 1: List candidate sources** for survivorship-free stock prices and for historical option quotes with bid/ask and earnings dates.
- [ ] **Step 2: For each, verify from the vendor's own pages** (not memory): history start, delisted names included, personal-use licence, price, sample or trial availability. Mark anything unverified as unverified.
- [ ] **Step 3: Post a comparison table** to #252 with a recommendation and what a coverage check on a sample would test. Create no account and spend nothing.

### Task 5: Q3 earnings-event options pilot (gated)

- [ ] **Step 1: Do not start** until the lead has named a spend cap and approved a vendor from Task 4.
- [ ] **Step 2: Open the Q3 issue and post the card** (defined-risk structures, a pilot on about 20 liquid stocks, quote-quality checks first, bid/ask cost model, baseline from Q1) and wait for the lead's reply before freezing.
- [ ] **Step 3: Run the pilot** and post the verdict comment; a pilot can show the data is usable or not, never a GO.

### Task 6: Stop-date review

- [ ] **Step 1: On 2027-01-18, or when Q1 to Q3 each have a Stage 1 verdict,** post the ledger and spend to date on #252.
- [ ] **Step 2: If no GO,** run a new brainstorm to choose between the trend baseline as the product, a research and watch tool, or a pause.

---

## Self-review notes

- Spec coverage: success definition (Tasks 2 to 5 cards and baseline), protocol and stages (cards in Tasks 2, 3, 5), queue (Tasks 2, 3, 5), data and budget gates (Tasks 4, 5), energy parking (Task 1; the hold on #244 and #245 is a release rule and needs no task), stop rule (Task 6), artifacts policy (Global Constraints and Architecture).
- Deferred on purpose: a shared evaluation helper. Build it only if Task 3 reuses code from the H1 run that Task 2 or later would copy again; decide at the end of Task 3.
