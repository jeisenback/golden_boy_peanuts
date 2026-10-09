# Plan — From Regime Screener to Actionable Signal

**Status:** PROPOSAL — for human-lead review
**Author:** Claude Code session, 2026-10-09
**Scope:** ordered work plan, no sprint cadence. Each step names what it unblocks and who decides.

---

## 1. Goal

> Measure whether a high edge score is worth acting on, and remove from the output
> everything that cannot be measured.

Done means:

1. A written answer exists to "when the crude vol regime scores high, does buying
   vol on the tradeable tickers pay after premium?" with a go / pivot / hold verdict.
2. Every nightly candidate is persisted somewhere durable, so a forward test accumulates.
3. The output contains only instruments whose option outcomes can be scored.

No new data source, API key, alert channel, or signal until steps 1 through 5 are done.

---

## 2. Findings That Drive the Plan (review of `origin/develop`, 2026-10-09)

| Finding | Evidence | Consequence |
|---|---|---|
| One score per instrument, copied to all three structures | `evaluate_strategies()` computes `edge_score` once per instrument and attaches it to `long_straddle`, `call_spread`, `put_spread` alike | The `structure` column is not a recommendation. #134 is the fix but needs outcome data first. |
| No candidate history exists anywhere | `pipeline-daily.yml` runs against an ephemeral Postgres service container; candidates are printed to the job log and the DB is destroyed | A forward test is impossible as built. Hard blocker. |
| #164 duplicates existing work | It specifies a new `outcome_tracking` table and depends on #159. `strategy_outcomes` already exists (#130) with `write_strategy_outcome()` / `fetch_pending_outcomes()`, and `src/core/backtest.py` already reports hit rate per edge-score quartile | Re-scope, do not re-build. |
| Only one real-sample validation exists | `docs/backtest_reports/212-ovx-gap-quartiles.md`: Q4 mean 10-day forward move 7.43% vs 5.3–5.7%, Spearman rho +0.095 | Measures move size, not move relative to what options priced in. The straddle thesis is untested either way. |
| Crude futures options cannot be backtested | Vendor evaluation (#170): Massive indexes historical contracts for USO, XLE, XOM, CVX; none for CL / BZ | WTI and Brent are signal sources, not tradeable targets. |
| Five computed features are never persisted | #173: `write_feature_set()` drops curve steepness, supply shock, insider conviction, narrative velocity, tanker disruption | Per-signal attribution is impossible until fixed. |

Pattern: eleven fetch functions feed one score with a 0.1 rank correlation. Inputs were
added for three phases without one output being measured. This plan is the first feedback loop.

---

## 3. Ordered Steps

Steps 1 and 2 are gates. Nothing after step 5 starts until step 1 has a verdict.

### Step 1. Vol ratio study (NEW ISSUE) — gate

Extend `scripts/ovx_gap_quartiles.py` so each row also carries realized-to-implied:

```
implied_move_pct = OVX/100 * sqrt(10/252) * 100
ratio            = realized_fwd_move_pct / implied_move_pct
```

Report per gap quartile: median ratio, mean ratio, share of days with ratio > 1.
Run on `CL=F` (signal source) and on `USO` closes (tradeable proxy), both against OVX.

| Q4 median ratio (USO) | Verdict | What it unlocks |
|---|---|---|
| > 1.10 | Straddle thesis alive | #134 straddle weights lean on vol gap as written |
| 0.90 – 1.10 | Indeterminate | Hold #134; posture stays "research shortlist" |
| < 0.90 | Buying vol on high-score days loses to premium | #134 pivots to directional spreads; direction signals become the thing to validate |

Caveats from #212 carry over: overlapping windows, continuous-contract rolls, OVX as proxy.
Descriptive; gates design, not capital. Size: one session. Depends on nothing. Decision: none.

### Step 2. Durable candidate persistence (NEW ISSUE) — gate, human decision

| Option | Cost | New vendor / secret | Recommendation |
|---|---|---|---|
| (a) Workflow commits a dated JSON snapshot (`data/candidates/YYYY-MM-DD.json`) to a `data` branch | ~1 session; `contents: write` on the workflow | None | **Recommended.** Zero vendors, diffable; the forward test becomes a file join. |
| (b) Hosted Postgres free tier; `DATABASE_URL` as a repo secret | ~1 session + account setup | Yes | Only if the DB should be the system of record now. |
| (c) GitHub Actions artifacts | trivial | None | Rejected: 90-day retention. |

Depends on the lead's choice. Without it, step 4 cannot start.

### Step 3. Reclassify `CL=F` / `BZ=F` as signal-only (NEW ISSUE) — human decision

Split `INSTRUMENTS_IN_SCOPE` into signal and tradeable sets; `evaluate_strategies()` emits
only tradeable. The "18 candidates" regression test becomes 12, which Decision Authority
reserves to the human lead. Size: one session. Depends on nothing.

### Step 4. Persist all FeatureSet fields (#173) — migration review

Five nullable NUMERIC columns on `feature_sets`; write and read round-trip. Needed before
step 5 can attribute outcomes to signals. Size: one to two sessions.

### Step 5. Outcome reconcile (#164, re-scoped)

Nightly script reads persisted candidates (step 2), fetches realized prices, writes to the
existing `strategy_outcomes` table. Hit = realized move vs implied move at generation.
Hit rate per quartile via the existing `run_backtest()`. Drop the #159 dependency and the
new-table AC. Depends on steps 2 and 4. Size: two sessions.

### Step 6. Structure-selection design spec (doc, fold into #134 as pre-work)

Per-structure signal profiles; ETF vs equity signal availability (USO and XLE have no
insiders); leg and max-debit rules. Direction of the straddle weights is set by the step 1
verdict. Size: one session. Depends on step 1.

### Step 7. Structure-specific edge scoring (#134)

Implementation of step 6. Depends on step 6 and a non-indeterminate step 1 verdict.

### Step 8. Expiration from event horizon (#135)

Replaces the constant 30 days. Independent of the gates; can run any time after step 3.

### Step 9. Massive historical options loader for USO/XLE/XOM/CVX (NEW ISSUE)

Mirrors `src/backtest/ovx_loader.py`. Needed for option P&L backtests, not for the
forward test or step 1. Size: two sessions. Depends on nothing; low urgency.

### Step 10. `data_quality` field on candidates (#131)

Flags which signals were defaulted to zero. Helps step 5 attribution. Size: one session.

---

## 4. Decisions Required From the Human Lead

1. **Step 2 persistence option.** (a) committed JSON snapshots or (b) hosted Postgres. Recommendation: (a).
2. **Step 3 instrument scope.** Confirm `CL=F` and `BZ=F` stop emitting candidates; approve the regression test change.
3. **Step 5 re-scope of #164.** Use `strategy_outcomes`; drop the `outcome_tracking` table AC and the #159 dependency.
4. **Step 4 migration review** when the PR is open.

---

## 5. Deferred, With Reason

| Issue | Title | Reason |
|---|---|---|
| #165 | Alerting on edge_score threshold | Alerts before a forward test manufacture confidence the data does not support |
| #169 | thinkorswim `.tst` ticket export | Needs legs and a max debit; neither exists before step 7 |
| #168 | REST API | No consumer yet |
| #167 | Expand universe (OXY, HAL, MRO, DVN, SLB) | More unmeasured outputs; wait for the forward test on four tickers |
| #159 | ML weight tuning | No training data until step 5 has run for a quarter |
| #174 | LiquidityGate | Second-order until a trade spec exists to gate |
| #133 | Pipeline scheduler | `pipeline-daily.yml` already does this; close or fold into step 2 |
| #200 | Remove Discord/webhook infra | Unrelated hygiene; pick up when convenient |
| — | Any new data source | None needed. CFTC Commitments of Traders is the only future candidate, and only if step 1 pivots to directional spreads and step 5 shows direction is the weak link |

---

## 6. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Step 2 undecided | Forward test never starts; step 5 blocked | Option (a) needs no account setup; decide first |
| Step 1 lands indeterminate | #134 has no empirical basis for weight direction | Ship the spec, hold the implementation, posture stays "shortlist" |
| Overlapping 10-day windows overstate step 1 confidence | Weak effect reads as strong | Report median and share > 1, not just mean; require 60+ trading days of forward data before any calibration claim |
| Snapshot commits pollute `develop` | Noisy history, conflicts | Dedicated `data` branch, never `develop` |
| USO tracks WTI imperfectly | USO ratio diverges from CL=F | The divergence is the finding: how much crude signal survives in the tradeable proxy |

---

## 7. Assumptions This Plan Tests

1. High edge score days are days when buying vol pays after premium. **Step 1.**
2. The crude regime signal survives in the tradeable proxy (USO). **Step 1, second run.**
3. Nightly candidates can be persisted with zero new vendors. **Step 2.**
4. The eleven existing feeds are sufficient; the gap is measurement, not inputs. **Step 5, after a quarter of outcomes.**

Set aside, interesting but not now: calendar spreads (in the PRD, never implemented),
multi-user access (turns trade specs into investment advice; stay single-user until decided),
CFTC positioning data.
