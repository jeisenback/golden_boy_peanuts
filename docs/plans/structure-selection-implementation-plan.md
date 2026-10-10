# Directional Spread Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the volatility-gap edge score with a signed direction score that ranks call and put spreads, and stop emitting long straddles.

**Architecture:** One pure function turns the four direction signals into a net in [-1, 1]. `compute_edge_score()` reads that net for the requested structure and applies an amplifier. `evaluate_strategies()` then emits at most one spread per tradeable instrument. All changes stay inside `strategy_evaluation_agent.py`; no module is added to `src/`.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, ruff, black, mypy strict. No new packages.

**Spec:** `docs/plans/structure-selection-spec.md` (merged in #233). Issue #134.

## Global Constraints

- Type hints on all public functions, mypy strict passes; black line length 100.
- No new packages and no schema, migration or PRD edits.
- `CL=F` and `BZ=F` stay signal-only; `TRADEABLE_INSTRUMENTS` is `["USO", "XLE", "XOM", "CVX"]`.
- `OptionStructure.LONG_STRADDLE` stays in the enum; the scoring path raises `ValueError` for it and for `CALENDAR_SPREAD`.
- Spec values: weights curve 0.25, supply 0.35, tanker 0.25, insider 0.15; dispersion weight 0.30, narrative weight 0.10 (narrative capped at 1.0); `_MIN_EDGE_SCORE` stays 0.10; expiry stays 30 days.
- Insider conviction applies to `XOM` and `CVX` only; USO and XLE ignore it.
- Commit format `<type>(<scope>): <description> (#134)`; `bash scripts/local_check.sh` exits 0 before every push.

## Review Focus

1. Conflicting signals that net to about zero produce no candidate, not two weak ones.
2. No direction signal at all, or no volatility-gap record, returns 0.0 and an empty list without raising.
3. A huge curve steepness (for example -0.5) clips to full strength and never exceeds a score of 1.0.
4. Passing `LONG_STRADDLE` or `CALENDAR_SPREAD` raises `ValueError`, never a silent zero.
5. An insider-selling signal flips XOM and CVX but leaves USO and XLE untouched.

---

### Task 1: Direction net

**Files:**
- Modify: `src/agents/strategy_evaluation/strategy_evaluation_agent.py` (constants near line 60; new function after the constants)
- Test: `tests/agents/strategy_evaluation/test_strategy_evaluation_agent.py` (new class `TestComputeDirectionNet`)

**Interfaces:**
- Produces: `compute_direction_net(instrument: str, *, supply_shock_probability: float | None, futures_curve_steepness: float | None, insider_conviction_score: float | None, tanker_disruption_index: float | None) -> float`, returns a value in [-1.0, 1.0]; positive means bullish crude.
- Produces constants: `_CURVE_FULL = 0.05` (a one-month spread of 5% of the front price maps to full strength; the signal is `(second - front) / front`), `_W_CURVE = 0.25`, `_W_SUPPLY = 0.35`, `_W_TANKER = 0.25`, `_W_INSIDER = 0.15`, `_INSIDER_COVERED = frozenset({"XOM", "CVX"})`.

- [ ] **Step 1: Write the failing tests.** In `TestComputeDirectionNet`, with spec values in the assertions (use `pytest.approx`):
  - supply 1.0 only gives 0.35; tanker 1.0 only gives 0.25.
  - curve -0.05 (backwardation) gives +0.25; curve +0.05 (contango) gives -0.25; curve -0.5 clips to +0.25.
  - XOM insider 0.9 gives 0.15 * 0.8 = 0.12; CVX insider 0.0 gives -0.15; USO and XLE with insider 0.9 give 0.0.
  - supply 0.5 with curve +0.035 nets to 0.0.
  - all four maxed bullish for XOM gives 1.0; all `None` gives 0.0.
- [ ] **Step 2: Run to verify failure.** `pytest tests/agents/strategy_evaluation/test_strategy_evaluation_agent.py::TestComputeDirectionNet -v`. Expected: FAIL, name not defined.
- [ ] **Step 3: Implement `compute_direction_net`** with the signature above. Clip the curve signal to [-1, 1] after dividing by `_CURVE_FULL`; map insider conviction `c` to `2c - 1`; a `None` input contributes 0.0.
- [ ] **Step 4: Run to verify pass.** Same command. Expected: all PASS.
- [ ] **Step 5: Commit.** `git add` both files; `git commit -m "feat(strategy-evaluation): add signed direction net (#134)"`.

### Task 2: Structure-specific `compute_edge_score`

**Files:**
- Modify: `src/agents/strategy_evaluation/strategy_evaluation_agent.py` (`compute_edge_score` at line 124; remove the constants that only the old formula used)
- Modify: `tests/agents/strategy_evaluation/test_strategy_evaluation_agent.py` (replace class `TestComputeEdgeScore`)
- Modify: `tests/agents/strategy_evaluation/test_strategy_evaluation_agent_integration.py` (the two `compute_edge_score` calls)

**Interfaces:**
- Consumes: `compute_direction_net` from Task 1.
- Produces: `compute_edge_score(instrument: str, feature_set: FeatureSet, option_structure: OptionStructure, supply_shock_probability: float | None = None, futures_curve_steepness: float | None = None, insider_conviction_score: float | None = None, narrative_velocity: float | None = None, tanker_disruption_index: float | None = None) -> float`.

- [ ] **Step 1: Write the failing tests** in a new `TestComputeEdgeScore`, replacing the old class:
  - supply 1.0 gives call spread 0.35 and put spread 0.0 for USO; curve +0.05 gives put 0.25 and call 0.0.
  - Amplifier: supply 1.0 with `sector_dispersion=0.5` gives 0.4025 (0.35 * 1.15); supply 1.0 with narrative 2.0 gives 0.385 (narrative capped to 1.0, so 0.35 * 1.10).
  - A maxed bullish setup with dispersion 0.5 and narrative 0.5 clamps to exactly 1.0.
  - Score is the same with and without a volatility-gap record, and 0.0 with no signals and no record.
  - `LONG_STRADDLE` and `CALENDAR_SPREAD` each raise `ValueError`.
- [ ] **Step 2: Run to verify failure.** `pytest tests/agents/strategy_evaluation/test_strategy_evaluation_agent.py::TestComputeEdgeScore -v`. Expected: FAIL.
- [ ] **Step 3: Implement the signature above.** Call spread returns `min(1.0, max(net, 0) * amp)`, put spread `min(1.0, max(-net, 0) * amp)`, with `amp = 1 + 0.30 * sector_dispersion + 0.10 * min(narrative_velocity, 1.0)` and a `None` input as 0.0. Add `_W_DISPERSION = 0.30` and `_W_NARRATIVE = 0.10`. Delete `_VOL_GAP_FULL_WEIGHT`, `_VOL_GAP_WEIGHT`, `_DISPERSION_WEIGHT`, `_SUPPLY_SHOCK_WEIGHT`, `_CURVE_STEEPNESS_WEIGHT`, `_INSIDER_CONVICTION_WEIGHT`, `_NARRATIVE_VELOCITY_WEIGHT`, `_TANKER_DISRUPTION_WEIGHT`, `_INSIDER_CONVICTION_HIGH_THRESHOLD` and `_CROSS_SECTOR_BOOST`, after a grep confirms nothing else imports them. Keep `_vol_gap_label` and the dispersion and supply-shock label thresholds.
- [ ] **Step 4: Update the two integration-test calls** to pass `OptionStructure.CALL_SPREAD`; the golden band moves in Task 3.
- [ ] **Step 5: Run to verify pass.** `pytest tests/agents/strategy_evaluation -m "not integration" -v`. Expected: Task 2 tests PASS; remaining failures are only in `TestEvaluateStrategies` (fixed in Task 3).
- [ ] **Step 6: Commit.** `git commit -m "feat(strategy-evaluation): structure-specific edge score (#134)"`.

### Task 3: Emit one directional spread per instrument

**Files:**
- Modify: `src/agents/strategy_evaluation/strategy_evaluation_agent.py` (`_PHASE_1_STRUCTURES` at line 68, `evaluate_strategies` at line 297)
- Modify: `tests/agents/strategy_evaluation/test_strategy_evaluation_agent.py` (class `TestEvaluateStrategies`)
- Modify: `tests/agents/strategy_evaluation/test_strategy_evaluation_agent_integration.py` (golden band)
- Modify: `README.md` (the Structures line)

**Interfaces:**
- Consumes: `compute_edge_score` from Task 2.
- Produces: `evaluate_strategies(feature_set: FeatureSet) -> list[StrategyCandidate]` (unchanged signature); `signals` gains key `"direction"` with value `"bullish"` or `"bearish"`.

- [ ] **Step 1: Write the failing tests** (replace `test_three_structures_per_instrument` and `test_correlated_instruments_yield_12_equal_score_candidates`):
  - Bullish feature set (supply 1.0, tanker 1.0, curve -0.05) yields 4 `call_spread` candidates at 0.85 in order USO, XLE, XOM, CVX; none for `CL=F` or `BZ=F`.
  - Contango +0.05 only yields 4 `put_spread` candidates at 0.25.
  - Supply 0.5 plus insider 0.0 yields only USO and XLE (XOM and CVX net to 0.025, below 0.10).
  - Supply 0.5 with contango +0.035 yields no candidates (the two signals cancel).
  - Every candidate's `signals["direction"]` matches its structure; no candidate is a `long_straddle`; at most one candidate per instrument.
  - An empty `FeatureSet` still returns `[]`; expiration is still 30.
- [ ] **Step 2: Run to verify failure.** `pytest tests/agents/strategy_evaluation/test_strategy_evaluation_agent.py::TestEvaluateStrategies -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Set `_PHASE_1_STRUCTURES` to `[CALL_SPREAD, PUT_SPREAD]`. For each tradeable instrument score both, keep those at or above `_MIN_EDGE_SCORE`, add `direction`, keep the sort and the persistence block as is. Update the docstring.
- [ ] **Step 4: Update the integration golden band.** Use a feature set with supply 0.8, curve -0.03 and dispersion 0.5, which scores 0.4945 for a USO call spread; set the floor, ceiling and golden min and max constants to bracket it, and assert a `call_spread` candidate for USO. Change the README line to `**Structures:** Call/put spreads (long straddles removed pending forward-test evidence; calendar spreads deferred)`.
- [ ] **Step 5: Run to verify pass.** `pytest tests/agents/strategy_evaluation -m "not integration" -v`. Expected: all PASS.
- [ ] **Step 6: Commit.** `git commit -m "feat(strategy-evaluation): emit one directional spread per instrument (#134)"`.

### Task 4: Backtest harness (blocked on Decision D7)

**Files:**
- Modify: `scripts/backtest_harness.py` (`replay_pipeline`, import at line 46)
- Modify: `tests/backtest/test_backtest_harness.py`, `docs/backtest_reports/2020-03-09.md`, `2022-02-24.md`, `2023-12-18.md`

**Interfaces:**
- Consumes: nothing from earlier tasks. The harness feeds only volatility gaps and dispersion, so the new scorer returns no candidates on its fixtures and the CI "edge above 60%" assertion would fail.
- Recommended approach (D7): move the old volatility-regime formula into the harness as a private `_legacy_vol_regime_score(instrument: str, feature_set: FeatureSet, supply_shock_probability: float | None, futures_curve_steepness: float | None) -> float` with its own private copies of the old constants, so the three replays and their assertion keep running unchanged. Label the reports "legacy volatility-regime replay, pre-#134". Offline fixtures carry no direction inputs, and inventing them would be a fabricated backtest.

- [ ] **Step 1: Write the failing test.** `replay_pipeline` for the high-IV state still yields candidates scoring above 0.60, and the report text says "legacy".
- [ ] **Step 2: Run to verify failure.** `pytest tests/backtest/test_backtest_harness.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `_legacy_vol_regime_score` with the pre-#134 formula and the replay loop calling it; add the "legacy" line to `write_backtest_report`.
- [ ] **Step 4: Regenerate reports.** `PYTHONPATH=. python scripts/backtest_harness.py`. Expected: 3/3 events pass.
- [ ] **Step 5: Final gate.** `bash scripts/local_check.sh`. Expected: ALL STAGES PASSED.
- [ ] **Step 6: Commit and push.** `git commit -m "chore(backtest): keep harness on the legacy volatility score (#134)"`; open the pull request.

---

## Notes and deviations from the spec

- Out of scope here: the signed hit and base-rate scoring belongs to plan step 5 (#164). Until it lands, `run_backtest()` still scores hits on the absolute move and cannot judge these spreads.
- Leg and debit fields on `StrategyCandidate` are deliberately not built (spec Decision 4, recommended option).
- The spec's formula has no cross-sector boost. This plan removes it (added in #158) with the rest of the volatility-led score. Decided 2026-10-10: drop it now and revisit after the forward test in #234.
- `_CURVE_FULL = 0.05` is set from the signal's units (a monthly spread as a fraction of the front price), not from observed data, because the repo holds no historical curve data. Recheck against the first snapshots.
- `scripts/uat_run.py` needs no code change; its baseline-versus-Phase-3 comparison will report `None` for the baseline, which it already tolerates.
