"""
Unit tests for fetch_eia_data() in the Event Detection Agent.

All HTTP calls are mocked — no real EIA API key or network required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.event_detection.event_detection_agent import fetch_eia_data
from src.agents.event_detection.models import EIAInventoryRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CRUDE_RESPONSE = {
    "response": {
        "data": [
            {"period": "2024-10", "value": "423.5"},
            {"period": "2024-09", "value": "418.2"},
        ]
    }
}

_REFINERY_RESPONSE = {
    "response": {
        "data": [
            {"period": "2024-10", "value": "87.4"},
            {"period": "2024-09", "value": "86.1"},
        ]
    }
}


def _mock_response(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = payload
    return mock


# ---------------------------------------------------------------------------
# Missing API key — degraded mode
# ---------------------------------------------------------------------------


class TestFetchEIADataDegradedMode:
    def test_missing_key_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EIA_API_KEY", raising=False)
        result = fetch_eia_data()
        assert result == []

    def test_missing_key_logs_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.delenv("EIA_API_KEY", raising=False)
        import logging

        with caplog.at_level(logging.WARNING):
            fetch_eia_data()
        assert any("EIA_API_KEY" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestFetchEIADataHappyPath:
    def test_returns_list_of_eia_inventory_records(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EIA_API_KEY", "test-key")
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(_CRUDE_RESPONSE),
                _mock_response(_REFINERY_RESPONSE),
            ]
            result = fetch_eia_data()

        assert len(result) == 2
        assert all(isinstance(r, EIAInventoryRecord) for r in result)

    def test_records_sorted_newest_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EIA_API_KEY", "test-key")
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(_CRUDE_RESPONSE),
                _mock_response(_REFINERY_RESPONSE),
            ]
            result = fetch_eia_data()

        assert result[0].period == "2024-10"
        assert result[1].period == "2024-09"

    def test_crude_stocks_and_refinery_merged_by_period(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EIA_API_KEY", "test-key")
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(_CRUDE_RESPONSE),
                _mock_response(_REFINERY_RESPONSE),
            ]
            result = fetch_eia_data()

        latest = next(r for r in result if r.period == "2024-10")
        assert latest.crude_stocks_mb == pytest.approx(423.5)
        assert latest.refinery_utilization_pct == pytest.approx(87.4)

    def test_fetched_at_is_utc_datetime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EIA_API_KEY", "test-key")
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(_CRUDE_RESPONSE),
                _mock_response(_REFINERY_RESPONSE),
            ]
            result = fetch_eia_data()

        for record in result:
            assert record.fetched_at.tzinfo is not None

    def test_source_defaults_to_eia(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EIA_API_KEY", "test-key")
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(_CRUDE_RESPONSE),
                _mock_response(_REFINERY_RESPONSE),
            ]
            result = fetch_eia_data()

        assert all(r.source == "eia" for r in result)

    def test_api_key_sent_in_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EIA_API_KEY", "my-secret-key")
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(_CRUDE_RESPONSE),
                _mock_response(_REFINERY_RESPONSE),
            ]
            fetch_eia_data()

        for c in mock_get.call_args_list:
            params = c.kwargs.get("params", {})
            assert params.get("api_key") == "my-secret-key"

    def test_eia_base_url_env_var_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EIA_API_KEY", "test-key")
        monkeypatch.setenv("EIA_BASE_URL", "http://eia-mock.internal")
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(_CRUDE_RESPONSE),
                _mock_response(_REFINERY_RESPONSE),
            ]
            fetch_eia_data()

        urls = [c.args[0] for c in mock_get.call_args_list]
        assert all(u.startswith("http://eia-mock.internal") for u in urls)


# ---------------------------------------------------------------------------
# Malformed / partial responses
# ---------------------------------------------------------------------------


class TestFetchEIADataMalformedResponse:
    def test_empty_data_array_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EIA_API_KEY", "test-key")
        empty = {"response": {"data": []}}
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(empty),
                _mock_response(empty),
            ]
            result = fetch_eia_data()

        assert result == []

    def test_null_value_in_series_yields_none_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EIA_API_KEY", "test-key")
        crude_with_null = {"response": {"data": [{"period": "2024-10", "value": None}]}}
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(crude_with_null),
                _mock_response({"response": {"data": []}}),
            ]
            result = fetch_eia_data()

        assert len(result) == 1
        assert result[0].crude_stocks_mb is None

    def test_missing_period_key_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EIA_API_KEY", "test-key")
        bad_crude = {"response": {"data": [{"value": "400.0"}]}}  # no period key
        with patch("requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_response(bad_crude),
                _mock_response({"response": {"data": []}}),
            ]
            result = fetch_eia_data()

        assert result == []

    def test_http_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import requests as req_mod

        monkeypatch.setenv("EIA_API_KEY", "test-key")
        error_resp = MagicMock()
        error_resp.raise_for_status.side_effect = req_mod.HTTPError("500")
        with patch("requests.get", return_value=error_resp):
            with pytest.raises(req_mod.HTTPError):
                fetch_eia_data()
