"""Unit tests for src/backtest/wti_loader.py. All tests run offline."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
import pytest
import requests

from src.backtest.wti_loader import fetch_wti_csv, load_wti, parse_wti_csv

_CSV = (
    "observation_date,DCOILWTICO\n"
    "2020-04-17,18.27\n"
    "2020-04-20,-36.98\n"
    "2020-04-21,.\n"
    "2020-04-22,\n"
    "2020-04-23,13.78\n"
)


def test_parse_wti_csv_drops_missing_rows_and_keeps_negative_price() -> None:
    obs = parse_wti_csv(_CSV)
    assert [(o.observation_date, o.value) for o in obs] == [
        (date(2020, 4, 17), 18.27),
        (date(2020, 4, 20), -36.98),
        (date(2020, 4, 23), 13.78),
    ]


def test_load_wti_slices_date_range_from_local_csv(tmp_path: Path) -> None:
    path = tmp_path / "wti.csv"
    path.write_text(_CSV, encoding="utf-8")
    series = load_wti(date(2020, 4, 18), date(2020, 4, 23), csv_path=path)
    assert series == {date(2020, 4, 20): -36.98, date(2020, 4, 23): 13.78}


def test_fetch_wti_csv_requests_series_and_range() -> None:
    response = MagicMock(text=_CSV)
    with patch("src.backtest.wti_loader.requests.get", return_value=response) as get:
        text = fetch_wti_csv(date(2020, 4, 1), date(2020, 4, 30))
    assert text == _CSV
    assert get.call_args.kwargs["params"] == {
        "id": "DCOILWTICO",
        "cosd": "2020-04-01",
        "coed": "2020-04-30",
    }


def test_fetch_wti_csv_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TENACITY_MAX_RETRIES", "1")
    response = MagicMock()
    response.raise_for_status.side_effect = requests.HTTPError("503")
    with patch("src.backtest.wti_loader.requests.get", return_value=response):
        with pytest.raises(requests.HTTPError):
            fetch_wti_csv(date(2020, 4, 1), date(2020, 4, 30))


def test_parse_wti_csv_raises_validation_error_on_malformed_price() -> None:
    with pytest.raises(ValidationError):
        parse_wti_csv("observation_date,DCOILWTICO\n2020-04-17,abc\n")


def test_load_wti_reads_event_window_fixture() -> None:
    fixture = Path("backtests/fixtures/wti_event_windows.csv")
    series = load_wti(date(2020, 1, 1), date(2023, 12, 31), csv_path=fixture)
    assert len(series) == 100
    for event_day in (date(2020, 3, 9), date(2022, 2, 24), date(2023, 12, 18)):
        assert event_day in series
    assert all(price > 0 for price in series.values())
