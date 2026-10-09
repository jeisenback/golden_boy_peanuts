# Sprint 10 Proposal — Actionable Signal Gate

**Status:** PROPOSAL — for human-lead review before `scripts/sprint_start.sh`
**Author:** Claude Code session, 2026-10-09
**Sprint length:** 1 week (per `docs/sprint_framework.md` §1)
**Team:** 1 human lead (decisions, merges, migration review) + AI agent sessions (implementation)

---

## 1. Sprint Goal

> Measure whether a high edge score is worth acting on, and remove from the output
> everything that cannot be measured.

Success at sprint end means three things are true:

1. A written answer exists to "when the crude vol regime scores high, does buying
   vol on the tradeable tickers pay after premium?" with a go / pivot / hold verdict.
2. Every nightly candidate is persisted somewhere durable, so a forward test can
   start accumulating on Day 1 of the following sprint.
3. The output contains only instruments whose option outcomes can be scored.

Nothing in this sprint adds a data source, an API key, an alert channel, or a signal.

---

## 2. Why This Sprint, Why Now

Findings from the 2026-10-09 review of `origin/develop`:

| Finding | Evidence | Consequence |
|---|---|---|
| One score per instrument, copied to all three structures | `evaluate_strategies()` computes `edge_score` once per instrument and attaches it to `long_straddle`, `call_spread`, `put_spread` alike | The `structure` column is not a recommendation. #134 is the fix but depends on outcome data. |
| No candidate history exists anywhere | `pipeline-daily.yml` runs against an ephemeral Postgres service container; candidates are printed to the job log and the DB is destroyed | The forward test (#164) is impossible as the system is built. This is the sprint's hard blocker. |
| `#164` as written duplicates existing work | It specifies a new `outcome_tracking` table and depends on #159 (ML tuner). `strategy_outcomes` already exists (#130) with `write_strategy_outcome()` / `fetch_pending_outcomes()`, and `src/core/backtest.py` already computes hit rate per edge-score quartile | #164 needs re-scoping, not re-building. |
| Only one real-sample validation exists | `docs/backtest_reports/212-ovx-gap-quartiles.md`: Q4 mean 10-day forward move 7.43% vs 5.3–5.7%, Spearman rho +0.095 | Measures the size of the move, not the move relative to what options already priced in. The straddle thesis is untested in either direction. |
| Crude futures options cannot be backtested | Vendor evaluation (#170): Massive has historical contract indexing for USO, XLE, XOM, CVX; none for CL / BZ | WTI and Brent are signal sources, not tradeable targets. |
| Five computed features are never persisted | #173: `write_feature_set()` drops `futures_curve_steepness`, `supply_shock_probability`, `insider_conviction_score`, `narrative_velocity`, `tanker_disruption_index` | Per-signal attribution in any forward test is impossible until fixed. |

Pattern to name: eleven fetch functions feed one score with a 0.1 rank correlation.
Inputs have been added for three phases without a single output being measured.
This sprint is the first feedback loop.

---

## 3. Gates (P0) — must clear before any structure or weight work

### G1. Vol ratio study (NEW ISSUE)

Extend `scripts/ovx_gap_quartiles.py` so each row also carries the realized-to-implied ratio:

```
implied_move_pct = OVX/100 * sqrt(10/252) * 100
ratio            = realized_fwd_move_pct / implied_move_pct
```

Report per gap quartile: median ratio, mean ratio, share of days with ratio > 1.
Run it twice: once on `CL=F` (the signal source, as today) and once on `USO` closes
(the tradeable proxy), both against OVX as the implied leg.

Decision table, applied to Q4 on USO:

| Q4 median ratio | Verdict | What it unlocks |
|---|---|---|
| > 1.10 | Straddle thesis alive | #134 straddle weights lean on vol gap as written |
| 0.90 – 1.10 | Indeterminate | Hold #134; product posture stays "research shortlist" |
| < 0.90 | Buying vol on high-score days loses to premium | #134 pivots to directional spreads; direction signals become the thing to validate |

Caveats carry over from #212: overlapping windows, continuous-contract rolls,
OVX as a proxy. The verdict is descriptive and gates design, not capital.

Size: S (one agent session). No new dependencies. Depends on nothing.

### G2. Durable candidate persistence (NEW ISSUE — human decision required)

The daily workflow must write candidates somewhere that survives the job. Options:

| Option | Cost | New vendor / secret | Recommendation |
|---|---|---|---|
| (a) Workflow commits a dated JSON snapshot (`data/candidates/YYYY-MM-DD.json`) to a `data` branch | ~1 session; needs `contents: write` on the workflow | None | **Recommended.** Zero vendors, diffable, the forward test becomes a file join. |
| (b) Hosted Postgres free tier, `DATABASE_URL` as a repo secret | ~1 session + account setup | Yes (new vendor) | Only if the lead wants the DB to be the system of record now. |
| (c) GitHub Actions artifacts | trivial | None | Rejected: default 90-day retention; a forward test needs longer. |

Size: S–M. Depends on the lead's choice at planning. Without this, #164 cannot start.

---

## 4. Sprint Backlog

| Priority | Item | Issue | Size | Depends on | Human decision |
|---|---|---|---|---|---|
| P0 | Vol ratio study (G1) | NEW | S | — | No |
| P0 | Durable candidate persistence (G2) | NEW | S–M | Option chosen | **Yes: option (a) or (b)** |
| P1 | Reclassify `CL=F` / `BZ=F` as signal-only; split `INSTRUMENTS_IN_SCOPE` into signal and tradeable sets; `evaluate_strategies()` emits only tradeable | NEW | S | — | **Yes: instrument scope; the "18 candidates" regression test becomes 12** |
| P1 | #164 re-scoped: nightly reconcile writes to existing `strategy_outcomes`; hit = realized move vs implied move at generation; drop #159 dependency; hit rate per quartile via existing `run_backtest()` | #164 | M | G2, #173 | **Yes: approve re-scope of AC** |
| P1 | Persist all FeatureSet fields | #173 | S–M | — | **Yes: migration review** |
| P1 | Structure-selection design spec (doc only): per-structure signal profiles, ETF vs equity signal availability (USO/XLE have no insiders), leg and max-debit rules | fold into #134 as pre-work | S | G1 verdict | No |
| P2 | Structure-specific edge scoring (implementation) | #134 | M | G1 verdict by mid-sprint | No |
| P2 | Expiration from event horizon | #135 | S–M | — | No |
| P2 | Massive historical options loader for USO/XLE/XOM/CVX (mirrors `src/backtest/ovx_loader.py`) | NEW | M | — | No |
| P2 | `data_quality` field on candidates | #131 | S | — | No |

Load: P0 + P1 is roughly six to seven agent sessions, which is the 70 percent target for a
one-week sprint. P2 items are stretch and are cut first.

### Explicitly deferred (not this sprint, with reason)

| Issue | Title | Reason |
|---|---|---|
| #165 | Alerting on edge_score threshold | Alerts before a forward test manufacture confidence the data does not support |
| #169 | thinkorswim `.tst` ticket export | Needs legs and a max debit; neither exists until #134 and the spec land |
| #168 | REST API | No consumer yet |
| #167 | Expand universe (OXY, HAL, MRO, DVN, SLB) | More unmeasured outputs; wait for the forward test on four tickers |
| #159 | ML weight tuning | No training data until #164 has run for a quarter |
| #174 | LiquidityGate | Valuable, but second-order until there is a trade spec to gate |
| #133 | Pipeline scheduler | `pipeline-daily.yml` already does this; recommend closing or re-scoping to G2 |
| #200 | Remove Discord/webhook infra | Unrelated hygiene; fine to pick up if capacity appears |
| — | Any new data source | None needed. CFTC Commitments of Traders is the only future candidate, and only if G1 pivots to directional spreads and the forward test shows direction is the weak link |

---

## 5. Decisions Required From the Human Lead (at planning, Day 1)

1. **G2 persistence option.** (a) committed JSON snapshots or (b) hosted Postgres. Recommendation: (a).
2. **Instrument scope.** Confirm `CL=F` and `BZ=F` become signal-only and stop emitting candidates. This changes a regression test (18 to 12 candidates), which Decision Authority reserves to you.
3. **#164 re-scope.** Approve replacing the `outcome_tracking` table AC with the existing `strategy_outcomes` table, and dropping the #159 dependency.
4. **#173 migration review** when the PR is open (adds five nullable NUMERIC columns to `feature_sets`).
5. **Milestone.** GitHub already has "Sprint 10 — Phase 3 Signal Computation" holding #134, #135, #173. Reuse it or rename; `sprint_start.sh` needs the exact name.
6. **HEARTBEAT reset.** The Sprint Issues table still shows Sprint 9 with every row Not Started while notes run to 2026-09-20. Agents may not edit table rows; this needs you.

---

## 6. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| G2 not decided on Day 1 | Forward test slips a full sprint; #164 blocked | Decide at planning; option (a) needs no account setup |
| G1 verdict lands in the indeterminate band | #134 has no empirical basis for weight direction | Do not build #134 weights on assumption; ship the spec, hold the implementation, posture stays "shortlist" |
| Overlapping 10-day windows overstate confidence in G1 | A weak effect reads as a strong one | Report median and share > 1, not just mean; label descriptive; require 60+ trading days of forward data before any calibration claim |
| Snapshot commits from CI pollute `develop` history | Noisy log, accidental conflicts | Write to a dedicated `data` branch, never `develop` |
| USO tracks WTI imperfectly (roll yield, contango drag) | USO ratio diverges from CL=F ratio | That divergence is itself the finding: it tells you how much of the crude signal survives in the tradeable proxy |
| Changing the 18-candidate regression test without approval | Violates Decision Authority | Listed as an explicit human decision above |

---

## 7. Definition of Done (per `docs/working_agreement.md` §4)

- [ ] All AC checkboxes checked on every closed issue
- [ ] `bash scripts/local_check.sh` exits 0 on every PR
- [ ] CI green on all stages
- [ ] G1 report committed to `docs/backtest_reports/` with the verdict table filled in
- [ ] At least one nightly run has written a durable candidate snapshot (G2 proven, not just merged)
- [ ] HEARTBEAT sprint notes appended (append-only, new dated block)

---

## 8. Key Dates (relative; sprint starts the Monday the lead runs `sprint_start.sh`)

| Day | Event |
|---|---|
| Day 1 | Planning; decisions 1–3 and 5–6 recorded; G1 and G2 issues created and refined via `refine_issue.sh` |
| Day 2 | G1 report in; G2 PR open |
| Day 3 | Mid-sprint check-in: G1 verdict decides whether #134 implementation is in or out; #173 migration review |
| Day 4 | #164 re-scoped reconcile running against the first snapshot |
| Day 5 | Review and retro via `sprint_close.sh`; Sprint 11 scope follows from the G1 verdict |

---

## 9. Assumptions This Sprint Tests (captured for the retro)

1. High edge score days are days when buying vol pays after premium. **Tested by G1.**
2. The crude regime signal survives in the tradeable proxy (USO). **Tested by G1's second run.**
3. Nightly candidates can be persisted with zero new vendors. **Tested by G2.**
4. The eleven existing feeds are sufficient; the gap is measurement, not inputs. **Tested over the following sprint once #164 runs.**

Set aside, interesting but not now: calendar spreads (in the PRD, never implemented),
multi-user access (turns trade specs into investment advice; keep single-user until decided),
CFTC positioning data.
