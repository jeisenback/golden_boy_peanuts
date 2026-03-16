"""
Unit tests for fetch_news_events() and fetch_gdelt_events().

Both functions make HTTP requests to external APIs; all network calls
are mocked via unittest.mock.patch so no API keys or connectivity are required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.event_detection.event_detection_agent import (
    fetch_gdelt_events,
    fetch_news_events,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NEWSAPI_ARTICLE = {
    "title": "OPEC cuts output by 1 million barrels per day",
    "description": "OPEC+ members agreed to reduce production.",
    "source": {"name": "Reuters"},
    "publishedAt": "2026-03-15T18:00:00Z",
    "url": "https://reuters.com/opec-cuts",
}

_GDELT_RAW_ARTICLE = {
    "title": "Oil supply disruption in Middle East",
    "url": "https://example.com/oil-disruption",
    "seendate": "20260315T180000Z",
    "domain": "example.com",
}


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import requests

        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


# ---------------------------------------------------------------------------
# fetch_news_events
# ---------------------------------------------------------------------------


class TestFetchNewsEvents:
    def test_missing_api_key_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No NEWSAPI_KEY → degraded mode, returns [] without making HTTP call."""
        monkeypatch.delenv("NEWSAPI_KEY", raising=False)
        with patch("requests.get") as mock_get:
            result = fetch_news_events()
        assert result == []
        mock_get.assert_not_called()

    def test_happy_path_returns_articles(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Valid API response returns the articles list."""
        monkeypatch.setenv("NEWSAPI_KEY", "test-key")
        mock_resp = _mock_response({"articles": [_NEWSAPI_ARTICLE, _NEWSAPI_ARTICLE]})
        with patch("requests.get", return_value=mock_resp):
            result = fetch_news_events()
        assert len(result) == 2
        assert result[0]["title"] == _NEWSAPI_ARTICLE["title"]

    def test_empty_articles_key_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """API response with no articles key returns []."""
        monkeypatch.setenv("NEWSAPI_KEY", "test-key")
        mock_resp = _mock_response({"status": "ok"})
        with patch("requests.get", return_value=mock_resp):
            result = fetch_news_events()
        assert result == []

    def test_http_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTTP 4xx/5xx raises after retries are exhausted."""
        import requests as req

        monkeypatch.setenv("NEWSAPI_KEY", "test-key")
        mock_resp = _mock_response({}, status_code=401)
        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(req.HTTPError):
                fetch_news_events()

    def test_request_includes_api_key_param(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The API key is passed as a query parameter named 'apiKey'."""
        monkeypatch.setenv("NEWSAPI_KEY", "my-secret-key")
        mock_resp = _mock_response({"articles": []})
        with patch("requests.get", return_value=mock_resp) as mock_get:
            fetch_news_events()
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["apiKey"] == "my-secret-key"

    def test_request_covers_last_24_hours(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The 'from' parameter is set (24-hour window)."""
        monkeypatch.setenv("NEWSAPI_KEY", "test-key")
        mock_resp = _mock_response({"articles": []})
        with patch("requests.get", return_value=mock_resp) as mock_get:
            fetch_news_events()
        _, kwargs = mock_get.call_args
        assert "from" in kwargs["params"]


# ---------------------------------------------------------------------------
# fetch_gdelt_events
# ---------------------------------------------------------------------------


class TestFetchGdeltEvents:
    def test_happy_path_returns_normalized_articles(self) -> None:
        """GDELT articles are returned with normalized publishedAt key."""
        mock_resp = _mock_response({"articles": [_GDELT_RAW_ARTICLE]})
        with patch("requests.get", return_value=mock_resp):
            result = fetch_gdelt_events()
        assert len(result) == 1
        article = result[0]
        assert article["title"] == "Oil supply disruption in Middle East"
        # seendate normalized to ISO 8601
        assert "2026-03-15" in article["seendate"]
        assert "publishedAt" in article  # unified key present

    def test_empty_articles_returns_empty_list(self) -> None:
        """GDELT response with no articles returns []."""
        mock_resp = _mock_response({"articles": []})
        with patch("requests.get", return_value=mock_resp):
            result = fetch_gdelt_events()
        assert result == []

    def test_missing_articles_key_returns_empty_list(self) -> None:
        """GDELT response missing 'articles' key returns []."""
        mock_resp = _mock_response({})
        with patch("requests.get", return_value=mock_resp):
            result = fetch_gdelt_events()
        assert result == []

    def test_http_error_propagates(self) -> None:
        """HTTP errors propagate after retries."""
        import requests as req

        mock_resp = _mock_response({}, status_code=503)
        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(req.HTTPError):
                fetch_gdelt_events()

    def test_uses_gdelt_base_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GDELT_BASE_URL env var is used for the request URL."""
        monkeypatch.setenv("GDELT_BASE_URL", "http://custom-gdelt.example.com/api/v2")
        mock_resp = _mock_response({"articles": []})
        with patch("requests.get", return_value=mock_resp) as mock_get:
            fetch_gdelt_events()
        url = mock_get.call_args.args[0]
        assert url.startswith("http://custom-gdelt.example.com/api/v2")

    def test_falls_back_to_default_gdelt_url_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falls back to api.gdeltproject.org when GDELT_BASE_URL is not set."""
        monkeypatch.delenv("GDELT_BASE_URL", raising=False)
        mock_resp = _mock_response({"articles": []})
        with patch("requests.get", return_value=mock_resp) as mock_get:
            fetch_gdelt_events()
        url = mock_get.call_args.args[0]
        assert url.startswith("http://api.gdeltproject.org")

    def test_malformed_seendate_preserved_as_is(self) -> None:
        """Articles with unparseable seendate are included with the raw value."""
        bad_article = {**_GDELT_RAW_ARTICLE, "seendate": "not-a-date"}
        mock_resp = _mock_response({"articles": [bad_article]})
        with patch("requests.get", return_value=mock_resp):
            result = fetch_gdelt_events()
        assert len(result) == 1
        assert result[0]["seendate"] == "not-a-date"
