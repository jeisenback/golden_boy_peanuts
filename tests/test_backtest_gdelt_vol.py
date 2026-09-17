import logging
import pathlib
from unittest.mock import patch

from backtests.backtest_gdelt_vol import _FALLBACK_CLOSE_PRICE, evaluate, replay_events_from_gdelt
import pandas as pd


def test_evaluate_sample(tmp_path) -> None:
    repo = pathlib.Path(__file__).resolve().parents[1]
    gdelt = repo / "backtests" / "sample_gdelt.csv"
    prices = repo / "backtests" / "sample_prices.csv"

    out = evaluate(gdelt, prices, threshold=2.0, hold=3)
    assert isinstance(out, dict)
    assert "events" in out and "non_events" in out
    assert all(k in out["events"] for k in ("count", "mean", "median", "std"))


def test_replay_events_from_gdelt_uses_fallback_price_and_warns_on_missing_data(
    tmp_path, caplog
) -> None:
    """Event date predates all price data (nothing to forward-fill from) →
    the reindex/ffill result is NaN, not an empty row, so the fallback must
    be keyed off NaN detection rather than row count. The fallback price
    should be used and a WARNING logged, not silently propagated as NaN."""
    gdelt_path = tmp_path / "gdelt.csv"
    prices_path = tmp_path / "prices.csv"
    pd.DataFrame({"date": ["2020-01-10"], "articles": [999]}).to_csv(gdelt_path, index=False)
    pd.DataFrame({"date": ["2020-02-01"], "close": [45.0]}).to_csv(prices_path, index=False)

    with (
        patch("backtests.backtest_gdelt_vol.detect_events") as mock_detect,
        patch("scripts.backtest_harness.replay_pipeline", return_value=[]) as mock_replay,
        caplog.at_level(logging.WARNING),
    ):
        mock_detect.return_value = pd.Series([True], index=pd.to_datetime(["2020-01-10"]))
        results = replay_events_from_gdelt(gdelt_path, prices_path)

    assert results == {"2020-01-10": []}
    mock_replay.assert_called_once()
    called_market_state = mock_replay.call_args[0][1]
    assert called_market_state.prices[0].price == _FALLBACK_CLOSE_PRICE
    assert any("no price data available" in r.message for r in caplog.records)


def test_replay_events_from_gdelt_uses_real_price_when_available(tmp_path) -> None:
    """Event date has a matching price row → the real close price is used,
    not the fallback."""
    gdelt_path = tmp_path / "gdelt.csv"
    prices_path = tmp_path / "prices.csv"
    pd.DataFrame({"date": ["2020-01-10"], "articles": [999]}).to_csv(gdelt_path, index=False)
    pd.DataFrame({"date": ["2020-01-10"], "close": [72.5]}).to_csv(prices_path, index=False)

    with (
        patch("backtests.backtest_gdelt_vol.detect_events") as mock_detect,
        patch("scripts.backtest_harness.replay_pipeline", return_value=[]) as mock_replay,
    ):
        mock_detect.return_value = pd.Series([True], index=pd.to_datetime(["2020-01-10"]))
        replay_events_from_gdelt(gdelt_path, prices_path)

    called_market_state = mock_replay.call_args[0][1]
    assert called_market_state.prices[0].price == 72.5
