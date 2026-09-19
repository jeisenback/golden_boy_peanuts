"""
Unit tests for src/backtest/ovx_loader.py and its harness fallback (issue #212).

All tests run offline against fixtures in backtests/fixtures/ or inline data.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import logging
import math
import pathlib as _pathlib
import sys as _sys
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
import pytest

from src.agents.ingestion.models import InstrumentType, MarketState, RawPriceRecord
from src.backtest.ovx_loader import (
    fetch_ovx_csv,
    historical_volatility_gap,
    load_closes_csv,
    load_ovx,
    parse_ovx_csv,
    realized_vol,
)

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
from scripts.backtest_harness import (  # type: ignore[import]
    FIXTURES_DIR,
    _build_feature_set,
    _load_ovx_context,
)

_OVX_FIXTURE = FIXTURES_DIR / "ovx_event_windows.csv"
_CLOSE_FIXTURE = FIXTURES_DIR / "cl_close_event_windows.csv"


def _alternating_closes(start: date, days: int, up: float = 0.01) -> dict[date, float]:
    """Closes moving +up / -up alternately: every log return has magnitude ~up."""
    closes: dict[date, float] = {}
    price = 100.0
    for i in range(days):
        closes[start + timedelta(days=i)] = price
        price *= math.exp(up if i % 2 == 0 else -up)
    return closes


def test_parse_ovx_csv_drops_missing_value_rows() -> None:
    text = (
        "observation_date,OVXCLS\n"
        "2022-02-23,50.51\n2022-02-24,.\n2022-02-25,\n2022-02-28,52.50\n"
    )
    obs = parse_ovx_csv(text)
    assert [(o.observation_date, o.value) for o in obs] == [
        (date(2022, 2, 23), 50.51),
        (date(2022, 2, 28), 52.50),
    ]


def test_parse_ovx_csv_rejects_non_positive_value() -> None:
    with pytest.raises(ValidationError):
        parse_ovx_csv("observation_date,OVXCLS\n2022-02-23,-3.0\n")


def test_load_ovx_slices_date_range_from_fixture() -> None:
    series = load_ovx(date(2022, 2, 22), date(2022, 2, 25), csv_path=_OVX_FIXTURE)
    assert set(series) == {date(2022, 2, d) for d in (22, 23, 24, 25)}
    assert series[date(2022, 2, 24)] == pytest.approx(49.04)


def test_fetch_ovx_csv_calls_fred_with_timeout() -> None:
    response = MagicMock(text="observation_date,OVXCLS\n")
    with patch("src.backtest.ovx_loader.requests.get", return_value=response) as get:
        assert fetch_ovx_csv(date(2022, 1, 1), date(2022, 3, 1)) == "observation_date,OVXCLS\n"
    kwargs = get.call_args.kwargs
    assert kwargs["params"]["id"] == "OVXCLS"
    assert kwargs["timeout"] > 0
    response.raise_for_status.assert_called_once()


def test_realized_vol_matches_known_series() -> None:
    closes = _alternating_closes(date(2022, 1, 1), 40, up=0.01)
    vol = realized_vol(closes, date(2022, 2, 9), window=20)
    assert vol is not None
    expected = 0.01 * math.sqrt(252)
    assert vol == pytest.approx(expected, rel=0.06)


def test_realized_vol_returns_none_when_history_too_short() -> None:
    closes = _alternating_closes(date(2022, 1, 1), 10)
    assert realized_vol(closes, date(2022, 1, 10), window=20) is None


def test_realized_vol_excludes_non_positive_close_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    closes = _alternating_closes(date(2020, 3, 20), 40, up=0.01)
    bad_day = date(2020, 4, 10)
    closes[bad_day] = -37.63
    with caplog.at_level(logging.WARNING, logger="src.backtest.ovx_loader"):
        vol = realized_vol(closes, date(2020, 4, 28), window=20)
    assert vol is not None
    assert not math.isnan(vol)
    assert any("2020-04-10" in rec.message for rec in caplog.records)


def test_historical_gap_on_ukraine_fixture_is_positive_and_in_fractions() -> None:
    ovx = load_ovx(date(2022, 1, 1), date(2022, 3, 1), csv_path=_OVX_FIXTURE)
    closes = load_closes_csv(_CLOSE_FIXTURE)
    gap = historical_volatility_gap("CL=F", date(2022, 2, 24), closes=closes, ovx=ovx)
    assert gap.implied_vol == pytest.approx(0.4904)
    assert 0.0 < gap.realized_vol < 1.0
    assert gap.gap == pytest.approx(gap.implied_vol - gap.realized_vol)
    assert gap.gap > 0.10
    assert gap.computed_at == datetime(2022, 2, 24, tzinfo=UTC)


def test_historical_gap_uses_prior_ovx_on_non_trading_day() -> None:
    ovx = load_ovx(date(2022, 1, 1), date(2022, 3, 1), csv_path=_OVX_FIXTURE)
    closes = load_closes_csv(_CLOSE_FIXTURE)
    gap = historical_volatility_gap("CL=F", date(2022, 2, 26), closes=closes, ovx=ovx)
    assert gap.implied_vol == pytest.approx(0.4950)


def test_historical_gap_raises_when_ovx_is_stale() -> None:
    closes = load_closes_csv(_CLOSE_FIXTURE)
    with pytest.raises(ValueError, match="OVX"):
        historical_volatility_gap(
            "CL=F", date(2022, 2, 24), closes=closes, ovx={date(2022, 1, 3): 40.0}
        )


def _state(prices: list[RawPriceRecord]) -> MarketState:
    return MarketState(
        snapshot_time=datetime(2022, 2, 24, tzinfo=UTC),
        prices=prices,
        options=[],
        ingestion_errors=[],
    )


_CL_PRICE = RawPriceRecord(
    instrument="CL=F",
    instrument_type=InstrumentType.CRUDE_FUTURES,
    price=92.81,
    timestamp=datetime(2022, 2, 24, tzinfo=UTC),
    source="fixture",
)


def test_harness_uses_ovx_when_priced_instrument_has_no_option_rows() -> None:
    ovx, closes = _load_ovx_context()
    feature_set = _build_feature_set(_state([_CL_PRICE]), ovx, closes)
    gaps = {g.instrument: g for g in feature_set.volatility_gaps}
    assert set(gaps) == {"CL=F"}
    assert gaps["CL=F"].implied_vol == pytest.approx(0.4904)


def test_harness_ovx_fallback_skips_instruments_absent_from_market_state() -> None:
    ovx, closes = _load_ovx_context()
    assert _build_feature_set(_state([]), ovx, closes).volatility_gaps == []


def test_harness_without_ovx_context_adds_no_gaps() -> None:
    assert _build_feature_set(_state([_CL_PRICE])).volatility_gaps == []


def test_load_ovx_context_returns_empty_when_fixture_missing(tmp_path: _pathlib.Path) -> None:
    assert _load_ovx_context(tmp_path) == ({}, {})
