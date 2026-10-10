"""Unit tests for scripts/_massive_common.py (issue #221): never record an API key in a URL."""

from __future__ import annotations

import pathlib as _pathlib
import sys as _sys

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1]))
from scripts._massive_common import strip_api_key  # type: ignore[import]


def test_strip_api_key_removes_the_parameter_and_keeps_the_rest() -> None:
    url = (
        "https://api.massive.com/v3/reference/options/contracts"
        "?underlying_ticker=BZ&as_of=2021-06-23&limit=100&apiKey=not-a-real-key&sort=ticker"
    )
    out = strip_api_key(url)
    assert "apiKey" not in out
    assert "AbC123xyz" not in out
    assert out == (
        "https://api.massive.com/v3/reference/options/contracts"
        "?underlying_ticker=BZ&as_of=2021-06-23&limit=100&sort=ticker"
    )


def test_strip_api_key_leaves_a_url_without_the_parameter_unchanged() -> None:
    url = "https://api.massive.com/v3/reference/options/contracts?underlying_ticker=USO&limit=100"
    assert strip_api_key(url) == url
