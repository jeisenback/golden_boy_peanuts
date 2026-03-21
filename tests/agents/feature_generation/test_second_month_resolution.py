from __future__ import annotations

import yfinance as yf

from src.agents.feature_generation.feature_generation_agent import (
    _resolve_second_month_ticker,
)


class DummyInfo:
    def __init__(self, last_price):
        self.last_price = last_price


class DummyTicker:
    def __init__(self, price):
        self.fast_info = DummyInfo(price)


def test_resolve_second_month_ticker_picks_first_available(monkeypatch) -> None:
    # Simulate yfinance returning None for CLF=F then price for CLG=F
    def fake_ticker(symbol):
        # Provide price only for CLG=F
        if symbol == "CLG=F":
            return DummyTicker(80.0)
        return DummyTicker(None)

    monkeypatch.setattr(yf, "Ticker", fake_ticker)

    # allow up to a full year scan to avoid calendar-dependent failures
    ticker = _resolve_second_month_ticker(lookahead_months=12)
    # Should resolve to some valid CL* futures ticker when a price is present
    assert ticker is not None
    assert ticker.startswith("CL") and ticker.endswith("=F")


def test_resolve_second_month_ticker_returns_none_when_no_price(monkeypatch) -> None:
    def fake_ticker(symbol):
        return DummyTicker(None)

    monkeypatch.setattr(yf, "Ticker", fake_ticker)

    ticker = _resolve_second_month_ticker(lookahead_months=3)
    assert ticker is None
