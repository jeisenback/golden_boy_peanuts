# OVX volatility-gap quartile study (issue #212)

Generated 2026-09-19 by `scripts/ovx_gap_quartiles.py`.

- Sample: 1644 trading days, 2020-01-01 to 2026-09-19, CL=F
- Excluded: any day whose 30-day lookback or 10-day forward window touches a non-positive close (1 such close(s): 2020-04-20)
- gap = OVX/100 - 20-day realized vol; forward move = |10-trading-day log return| (%)

| Quartile | Gap range | Mean fwd move % | N |
|---|---|---:|---:|
| Q1 | -0.835 to -0.001 | 5.33 | 411 |
| Q2 | -0.001 to +0.054 | 5.44 | 411 |
| Q3 | +0.054 to +0.101 | 5.69 | 411 |
| Q4 | +0.101 to +0.476 | 7.43 | 411 |

Spearman rank correlation, gap vs forward move: +0.095

## Caveats
- Overlapping 10-day windows make observations serially correlated; treat the differences as descriptive, not statistically tested.
- Continuous CL=F contains contract rolls that add noise to realized vol.
- OVX is a crude-wide implied-vol proxy; no option P&L is reconstructed.
