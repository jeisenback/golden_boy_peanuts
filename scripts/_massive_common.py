"""Shared helpers for the Massive/Polygon vendor-evaluation scan scripts (issue #221)."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_API_KEY_PARAM = "apiKey"


def strip_api_key(url: str) -> str:
    """
    Return `url` with the `apiKey` query parameter removed.

    Args:
        url: A request URL as returned by `requests.Response.url`.

    Returns:
        The same URL without `apiKey`; other parameters keep their order. Recorded
        sample files must never carry the key (GitGuardian finding on PR #220).
    """
    parts = urlsplit(url)
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != _API_KEY_PARAM
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))
