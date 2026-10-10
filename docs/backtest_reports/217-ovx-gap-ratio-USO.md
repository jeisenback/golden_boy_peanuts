# OVX volatility-gap quartile study — USO (issues #212, #217)

Generated 2026-10-10 by `scripts/ovx_gap_quartiles.py --ticker USO`.

- Sample: 1692 trading days, 2020-01-01 to 2026-10-10, USO
- Excluded: any day whose 30-day lookback or 10-day forward window touches a non-positive close (0 such close(s): none)
- gap = OVX/100 - 20-day realized vol; fwd move = |10-trading-day log return| (%)
- implied move = OVX/100 * sqrt(10/252) * sqrt(2/pi) * 100, the expected absolute move a straddle's fair premium pays for; ratio = fwd move / implied move

| Quartile | Gap range | Mean fwd move % | Mean ratio | Median ratio | Share ratio > 1 | N |
|---|---|---:|---:|---:|---:|---:|
| Q1 | -0.670 to +0.036 | 7.06 | 0.821 | 0.660 | 0.286 | 423 |
| Q2 | +0.036 to +0.082 | 4.77 | 0.778 | 0.642 | 0.286 | 423 |
| Q3 | +0.082 to +0.129 | 5.71 | 0.913 | 0.707 | 0.326 | 423 |
| Q4 | +0.129 to +1.765 | 6.81 | 0.850 | 0.615 | 0.288 | 423 |
| All | -0.670 to +1.765 | 6.09 | 0.840 | 0.655 | 0.297 | 1692 |

Fair-pricing baseline (normal returns, options priced exactly right): mean ratio 1.000, median ratio 0.845, share > 1 of 0.425. Read each quartile against those, not against zero.

Spearman rank correlation, gap vs forward move: +0.068

## Verdict (plan step 1, applied to Q4 mean ratio)

Q4 mean ratio 0.850 -> BUYING VOL LOSES TO PREMIUM: top-quartile realized move does not cover the priced-in move; #134 pivots to directional spreads.

## Caveats
- Overlapping 10-day windows make observations serially correlated; treat the differences as descriptive, not statistically tested.
- Continuous futures contain contract rolls that add noise to realized vol; an ETF proxy adds roll yield and tracking error instead.
- OVX is a crude-wide implied-vol proxy, not the ticker's own option chain; no option P&L is reconstructed.
- The implied leg assumes normal returns; fat tails raise the fair mean ratio above 1.
