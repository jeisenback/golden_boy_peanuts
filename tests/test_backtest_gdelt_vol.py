from __future__ import annotations

import pathlib

from backtests.backtest_gdelt_vol import evaluate


def test_evaluate_basic(tmp_path: pathlib.Path):
    gdelt_csv = tmp_path / "gdelt.csv"
    prices_csv = tmp_path / "prices.csv"

    gdelt_csv.write_text(
        "date,articles\n2021-01-01,10\n2021-01-02,12\n2021-01-03,50\n2021-01-04,14\n"
    )
    prices_csv.write_text(
        "date,close\n2021-01-01,100\n2021-01-02,101\n2021-01-03,98\n2021-01-04,102\n"
    )

    out = evaluate(gdelt_csv, prices_csv, threshold=1.0, hold=2)
    assert "events" in out and "non_events" in out
    assert isinstance(out["events"], dict)
    assert all(k in out["events"] for k in ("count", "mean", "std"))
