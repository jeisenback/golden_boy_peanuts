# Spec: Structure Selection and Directional Scoring

**Status:** PROPOSAL for human-lead review. Nothing here is implemented or approved.
**Issue:** #134 (pre-work, plan step 6). Implementation is plan step 7 and starts only after this is approved.
**Author:** Claude Code session, 2026-10-10
**Decision already made:** drop long straddles from the output (human lead, 2026-10-10).

---

## 1. Why

The step 1 study (`docs/backtest_reports/217-ovx-gap-ratio-USO.md`, 1692 trading days) asked whether
buying volatility on high-gap days pays more than the options had already priced in. It does not.

| Measure (USO) | Result | Fair baseline |
|---|---|---:|
| Top gap quartile, mean ratio | 0.850 | 1.000 |
| All days, mean ratio | 0.840 | 1.000 |
| Gap vs forward move, rank correlation | +0.068 | none |

Under the plan's rule (top-quartile ratio below 0.90), #134 pivots to directional spreads and direction
signals become the thing to validate. The same study on WTI was indeterminate (1.001), so USO is the
reading the plan uses.

What the study does not show: whether any direction signal works. It tested move size, not direction.
Everything below is a heuristic until the forward test (#218, then plan step 5) measures it.

## 2. Current state (verified in `strategy_evaluation_agent.py`)

- `evaluate_strategies()` computes one score per instrument and attaches it to all three structures.
- 70% of the base score is the volatility gap, the signal the study found carries no edge.
- The score returns 0.0 when the instrument has no volatility-gap record, so option data gates every candidate.
- The curve term uses the absolute value of steepness, which discards direction.
- No signal today distinguishes a bullish view from a bearish one.

## 3. Proposal

### 3.1 Structures emitted

Emit `call_spread` and `put_spread` only. Remove `long_straddle` from `_PHASE_1_STRUCTURES`.
The enum value stays: it is a PRD structure and historical rows may reference it.
Passing `long_straddle` to the new scoring path raises `ValueError`.

### 3.2 Direction signal map

Each signal is mapped to a score `s` in [-1, 1], where positive means bullish crude.

| Signal | Range today | Reads as | Applies to | Notes |
|---|---|---|---|---|
| `futures_curve_steepness` | signed, positive = contango | backwardation bullish, contango bearish | all four | `s = clip(-steepness / _CURVE_FULL, -1, 1)` |
| `supply_shock_probability` | [0, 1] | bullish only | all four | no bearish counterpart exists |
| `tanker_disruption_index` | [0, 1] | bullish only | all four | supply disruption |
| `insider_conviction_score` | [0, 1], 2/3 neutral (#237) | above 2/3 bullish, below bearish | XOM, CVX only | `s = (c - 2/3) / (2/3)` for `c <= 2/3`, else `(c - 2/3) / (1/3)`; USO and XLE have no insiders |
| `narrative_velocity` | 0 or more | none | all four | magnitude only |
| `sector_dispersion` | [0, 1] | none | all four | magnitude only |
| `volatility_gap` | signed | none | per instrument | demoted to a label in `signals`; weight 0 |

`_CURVE_FULL` is a named constant. Its value must come from the observed range of the signal, which this
spec does not have. Set it from one look at real data during step 7, and record the value and source.

### 3.3 Scoring

```
direction_net = w_curve*s_curve + w_supply*s_supply + w_tanker*s_tanker + w_insider*s_insider
                (a missing signal contributes 0, as everywhere else in this module)
amplifier     = 1 + w_disp*sector_dispersion + w_narr*min(narrative_velocity, 1)
call_spread score = min(1, max(direction_net, 0) * amplifier)
put_spread  score = min(1, max(-direction_net, 0) * amplifier)
```

Starting weights, all heuristic and unvalidated: curve 0.25, supply 0.35, tanker 0.25, insider 0.15
(sum 1.0); dispersion 0.30, narrative 0.10 (the existing values). `_MIN_EDGE_SCORE` stays at 0.10.

**Amendment (#237):** the insider neutral point is 2/3, not 0.5. The score weights sells at half the
value of buys (`_BUY_WEIGHT` 1.0, `_SELL_WEIGHT` 0.5), so equal-dollar buying and selling scores 2/3. The
mapping is now centered there, so balanced insider activity adds nothing to the direction net.

**Amendment (#240):** the curve weight is 0.0, not 0.25. A 1986 to 2024 backtest of the curve against
30-day forward WTI spot returns found the opposite of the mapping above: deep contango (steepness of at
least +2%) preceded stronger returns (significant at the episode level), and deep backwardation preceded
weaker returns (not significant). The mapping and the other weights are unchanged, so the maximum net is
0.75, and the curve is still reported in `signals` so the forward test can validate or flip it.

Consequences:
- For one instrument only one side can be above zero, so a run emits **at most one spread per instrument,
  at most 4 candidates**, not 8. A call and a put spread are opposite bets, and ranking both on the same
  instrument would hide that. No directional view means no candidate.
- Direction signals no longer need option data, so the zero-return on a missing volatility-gap record goes away.
- `signals` gains `direction` ("bullish" or "bearish"). Still `dict[str, str]`, so the snapshot format is unchanged.

### 3.4 Instrument availability

| Instrument | Curve | Supply shock | Tanker | Insider |
|---|---|---|---|---|
| USO | yes | yes | yes | no |
| XLE | yes | yes | yes | no |
| XOM | yes | yes | yes | yes |
| CVX | yes | yes | yes | yes |

The crude signals are the same for all four. Equities respond to crude with a beta below 1 and with their
own factors. This spec does not scale the signal per instrument; the forward test will show whether it should.

### 3.5 Legs and maximum debit (rules, not yet fields)

Defaults, to be tuned only after the forward test:
- Call spread: buy the call nearest spot, sell the call about 5% above spot, same expiry.
- Put spread: buy the put nearest spot, sell the put about 5% below spot, same expiry.
- Maximum debit: 50% of the strike width, so the best case pays at least 1 to 1.
- Expiry stays at 30 calendar days. Event-driven expiry is #135, out of scope.

The 5% matches `_HIT_THRESHOLD` in `src/core/backtest.py`, so the hit definition and the structure agree.
Whether `StrategyCandidate` carries leg fields is Decision 4.

### 3.6 Validation

- **Hit:** the signed move over the horizon is at least 5% in the predicted direction.
- **Baseline:** for each instrument, the share of 30-day windows with a signed move of at least 5% in that
  direction. A signal only counts if its hit rate beats this base rate.
- **Minimum data:** 60 trading days of forward snapshots before any calibration claim (plan, risks table).
- **Dependency:** `run_backtest()` in `src/core/backtest.py` scores hits on the absolute move, which is a
  straddle definition. It cannot validate directional spreads until a signed variant exists. That change
  belongs to plan step 5 (#164) and must land before step 7 can be judged.

## 4. Impact on existing work

- `compute_edge_score()` gains an `option_structure` parameter (the #134 acceptance criterion). That is a
  public signature change, in scope for #134.
- Regression test: the 12-candidate test changes again. With equal inputs it will now yield at most 4.
- Replay reports, README structure line, and the candidate snapshot docs need updates.
- The PRD lists long straddles as an MVP structure. PRD edits are human-owned.
- The backtest harness replay uses the same scoring and must follow.

## 5. Out of scope

Demand-side signals, calendar spreads, ML weight tuning (#159), event-driven expiry (#135), alerts, a trade
ticket export (#169), and any new data source.

## 6. Risks and limits

- **Thin bearish side.** Every directional input except curve contango and insider selling reads bullish.
  Put spreads will rarely trigger, and the model will lean long crude. A demand-side signal (inventories,
  already ingested into `eia_inventory` but never turned into a feature) would fix this. No new vendor needed.
- **Four correlated bets.** USO, XLE, XOM and CVX will often agree. Four candidates may be one bet. See #132.
- **Unvalidated direction.** The study gives no evidence for any weight above. Treat the output as a research
  shortlist until the forward test says otherwise.

## 7. Decisions required from the human lead

1. **Candidate count.** One dominant side per instrument, at most 4 per run (recommended), or emit both sides
   and rank each by its own score. This sets the next regression test value.
2. **PRD.** Approve removing long straddles from the MVP structure list. The edit is yours.
3. **Starting weights and `_CURVE_FULL`.** Accept the weights in 3.3 as heuristics, and `_CURVE_FULL` as set from
   observed data in step 7.
4. **Legs and debit.** Carry them as optional fields on `StrategyCandidate` now, or only after the forward test
   (recommended). A model change here would also touch the snapshot and database layers.
5. **Signed hit.** Approve the hit and baseline definition in 3.6 so #164 can build it.
6. **Bearish coverage.** Ship with the thin put side (recommended, flagged in the output), or build the
   inventory feature first.
