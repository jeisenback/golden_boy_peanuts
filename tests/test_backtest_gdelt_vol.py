import pathlib

from backtests.backtest_gdelt_vol import evaluate


def test_evaluate_sample(tmp_path) -> None:
    repo = pathlib.Path(__file__).resolve().parents[1]
    gdelt = repo / "backtests" / "sample_gdelt.csv"
    prices = repo / "backtests" / "sample_prices.csv"

    out = evaluate(gdelt, prices, threshold=2.0, hold=3)
    assert isinstance(out, dict)
    assert "events" in out and "non_events" in out
    assert all(k in out["events"] for k in ("count", "mean", "median", "std"))
