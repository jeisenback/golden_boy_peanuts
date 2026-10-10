"""
WTI spot price loader from FRED for backtesting.

Series DCOILWTICO (daily, USD per barrel) is fetched from FRED's keyless CSV
endpoint. The returned dict has the same shape as ovx_loader.load_closes_csv,
so it can be passed straight to ovx_loader.realized_vol.

Unlike OVX, WTI spot can be zero or negative (-36.98 on 2020-04-20), so
values are not constrained to be positive. realized_vol already excludes
non-positive closes when computing log returns.
"""

from __future__ import annotations

import csv
from datetime import date
import io
from pathlib import Path

from pydantic import BaseModel
import requests

from src.core.retry import with_retry

FRED_CSV_URL: str = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_FRED_SERIES: str = "DCOILWTICO"
_HTTP_TIMEOUT_SECONDS: int = 30


class WtiObservation(BaseModel):
    """One validated daily WTI spot price, in USD per barrel."""

    observation_date: date
    value: float


@with_retry()
def fetch_wti_csv(start: date, end: date) -> str:
    """
    Download the DCOILWTICO CSV from FRED for [start, end].

    Raises:
        requests.HTTPError: after retries are exhausted on a non-2xx response.
    """
    response = requests.get(
        FRED_CSV_URL,
        params={"id": _FRED_SERIES, "cosd": start.isoformat(), "coed": end.isoformat()},
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.text


def parse_wti_csv(text: str) -> list[WtiObservation]:
    """
    Parse FRED DCOILWTICO CSV text into validated observations.

    FRED marks non-trading days with '.'; those rows (and blanks) are dropped.
    """
    observations: list[WtiObservation] = []
    for row in csv.DictReader(io.StringIO(text)):
        raw = (row.get(_FRED_SERIES) or "").strip()
        if raw in ("", "."):
            continue
        observations.append(
            WtiObservation(
                observation_date=date.fromisoformat(row["observation_date"]),
                value=float(raw),
            )
        )
    return observations


def load_wti(
    start: date,
    end: date,
    csv_path: Path | None = None,
) -> dict[date, float]:
    """
    Return WTI spot prices keyed by date for start <= date <= end.

    Args:
        start:    First date to include.
        end:      Last date to include.
        csv_path: Read this local FRED-format CSV instead of calling FRED
            (used by tests and offline backtests).
    """
    text = csv_path.read_text(encoding="utf-8") if csv_path else fetch_wti_csv(start, end)
    return {
        obs.observation_date: obs.value
        for obs in parse_wti_csv(text)
        if start <= obs.observation_date <= end
    }
