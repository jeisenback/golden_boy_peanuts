# OVX volatility-gap quartile study — CL=F (issues #212, #217)

Generated 2026-10-10 by `scripts/ovx_gap_quartiles.py --ticker CL=F`.

- Closes: FRED WTI spot (DCOILWTICO), not futures; the contract-roll caveat below does not apply to this run
- Sample: 1648 trading days, 2020-01-01 to 2026-10-10, CL=F
- Excluded: any day whose 30-day lookback or 10-day forward window touches a non-positive close (1 such close(s): 2020-04-20)
- gap = OVX/100 - 20-day realized vol; fwd move = |10-trading-day log return| (%)
- implied move = OVX/100 * sqrt(10/252) * sqrt(2/pi) * 100, the expected absolute move a straddle's fair premium pays for; ratio = fwd move / implied move

| Quartile | Gap range | Mean fwd move % | Mean ratio | Median ratio | Share ratio > 1 | N |
|---|---|---:|---:|---:|---:|---:|
| Q1 | -1.139 to +0.000 | 5.67 | 0.735 | 0.646 | 0.282 | 412 |
| Q2 | +0.000 to +0.055 | 5.71 | 0.874 | 0.685 | 0.316 | 412 |
| Q3 | +0.055 to +0.107 | 5.78 | 0.929 | 0.723 | 0.374 | 412 |
| Q4 | +0.107 to +0.478 | 7.38 | 1.001 | 0.753 | 0.342 | 412 |
| All | -1.139 to +0.478 | 6.14 | 0.885 | 0.700 | 0.328 | 1648 |

Fair-pricing baseline (normal returns, options priced exactly right): mean ratio 1.000, median ratio 0.845, share > 1 of 0.425. Read each quartile against those, not against zero.

Spearman rank correlation, gap vs forward move: +0.083

## Verdict (plan step 1, applied to Q4 mean ratio)

Q4 mean ratio 1.001 -> INDETERMINATE: within the 0.90-1.10 band; hold #134, posture stays "research shortlist".

## Caveats
- Overlapping 10-day windows make observations serially correlated; treat the differences as descriptive, not statistically tested.
- Continuous futures contain contract rolls that add noise to realized vol; an ETF proxy adds roll yield and tracking error instead.
- OVX is a crude-wide implied-vol proxy, not the ticker's own option chain; no option P&L is reconstructed.
- The implied leg assumes normal returns; fat tails raise the fair mean ratio above 1.
