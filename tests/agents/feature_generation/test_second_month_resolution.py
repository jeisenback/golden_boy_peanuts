"""
Second-month WTI contract resolution (issue #238).

Yahoo serves only the continuous front contract as ``CL=F``. Explicit contracts use
``CL<month code><yy>.NYM`` (for example ``CLZ26.NYM``). Expired contracts return no data,
so the first contract that has a price is the front month and the one after it is the
second month. The old probe used ``CL<code>=F`` symbols, which Yahoo never serves.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import yfinance as yf

from src.agents.feature_generation import feature_generation_agent as fga
from src.agents.feature_generation.feature_generation_agent import (
    _contract_ticker,
    _fetch_second_month_price,
    _resolve_second_month_ticker,
)


class _FakeInfo:
    """Mimics yfinance: reading last_price on a contract with no data raises KeyError."""

    def __init__(self, price: float | None) -> None:
        self._price = price

    @property
    def last_price(self) -> float:
        if self._price is None:
            raise KeyError("currentTradingPeriod")
        return self._price


class _FakeTicker:
    def __init__(self, price: float | None) -> None:
        self.fast_info = _FakeInfo(price)


def _priced(monkeypatch: pytest.MonkeyPatch, prices: dict[str, float]) -> None:
    """Make yf.Ticker return a price only for the given symbols."""
    monkeypatch.setattr(yf, "Ticker", lambda symbol: _FakeTicker(prices.get(symbol)))


def test_contract_ticker_uses_explicit_month_and_two_digit_year() -> None:
    assert _contract_ticker(2026, 12) == "CLZ26.NYM"
    assert _contract_ticker(2027, 1) == "CLF27.NYM"


def test_second_month_is_the_contract_after_the_front(monkeypatch: pytest.MonkeyPatch) -> None:
    # 2026-10-10: October has expired, so November (X26) is the front and December the second.
    _priced(monkeypatch, {"CLX26.NYM": 91.85, "CLZ26.NYM": 91.01, "CLF27.NYM": 90.0})
    now = datetime(2026, 10, 10, tzinfo=UTC)
    assert _resolve_second_month_ticker(now=now) == "CLZ26.NYM"


def test_an_expired_front_contract_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    # 2026-10-24: November has just expired (no data), so December is the front.
    _priced(monkeypatch, {"CLZ26.NYM": 91.01, "CLF27.NYM": 90.0, "CLG27.NYM": 88.83})
    now = datetime(2026, 10, 24, tzinfo=UTC)
    assert _resolve_second_month_ticker(now=now) == "CLF27.NYM"


def test_second_month_rolls_over_the_year(monkeypatch: pytest.MonkeyPatch) -> None:
    # 2026-12-05: January 2027 is the front, so February 2027 is the second.
    _priced(monkeypatch, {"CLF27.NYM": 90.0, "CLG27.NYM": 88.83})
    now = datetime(2026, 12, 5, tzinfo=UTC)
    assert _resolve_second_month_ticker(now=now) == "CLG27.NYM"


def test_resolution_returns_none_when_no_contract_has_a_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _priced(monkeypatch, {})
    assert (
        _resolve_second_month_ticker(lookahead_months=3, now=datetime(2026, 10, 10, tzinfo=UTC))
        is None
    )


def test_fetch_returns_the_price_of_the_resolved_second_month(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fga, "_resolve_second_month_ticker", lambda: "CLZ26.NYM")
    _priced(monkeypatch, {"CLZ26.NYM": 91.01})
    assert _fetch_second_month_price() == pytest.approx(91.01)


def test_fetch_raises_instead_of_guessing_a_symbol_when_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fga, "_resolve_second_month_ticker", lambda: None)
    monkeypatch.setattr(_fetch_second_month_price.retry, "sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match="second-month"):
        _fetch_second_month_price()
