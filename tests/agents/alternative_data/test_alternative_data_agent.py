"""
Unit tests for fetch_edgar_insider_trades (issue #149).

Tests use mocked HTTP responses — no real EDGAR API calls.
Integration tests (real network) belong in a separate integration test file.

Coverage:
  - Happy path: EFTS hit → XML fetch → parse → InsiderTrade records returned
  - Malformed XML: parse error logged as WARNING, empty list returned
  - Empty EFTS result: no hits, empty list returned
  - HTTP error propagates: RequestException raised for tenacity retry
  - Instrument filter: only specified instruments searched
  - Unmapped transaction code: skipped silently (no InsiderTrade for "F")
  - Missing officer name: officer_name=None allowed
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.agents.alternative_data.alternative_data_agent import (
    _efts_search,
    _parse_form4_xml,
    fetch_edgar_insider_trades,
)
from src.agents.alternative_data.models import InsiderTrade

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


def _make_efts_response(ticker: str, cik: str = "34088") -> dict:
    """Minimal EFTS JSON with one Form 4 hit."""
    return {
        "hits": {
            "hits": [
                {
                    "_id": "0001610717-24-000004",
                    "_source": {
                        "entity_id": cik.zfill(10),
                        "form_type": "4",
                        "file_date": "2024-01-17",
                        "period_of_report": "2024-01-15",
                    },
                }
            ]
        }
    }


_FILING_INDEX = {
    "directory": {
        "item": [
            {"name": "wf-form4_20240117.xml", "type": "4"},
            {"name": "wf-form4_20240117.htm", "type": "4"},
        ]
    }
}

_FORM4_XML_BUY = """<?xml version="1.0"?>
<ownershipDocument>
  <periodOfReport>2024-01-15</periodOfReport>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerName>DOE JOHN</rptOwnerName>
    </reportingOwnerId>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2024-01-15</value></transactionDate>
      <transactionCoding>
        <transactionCode>P</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>110.00</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

_FORM4_XML_SELL = _FORM4_XML_BUY.replace(
    "<transactionCode>P</transactionCode>",
    "<transactionCode>S</transactionCode>",
)


def _mock_resp(payload: dict | str, status: int = 200) -> MagicMock:
    """Return a mock requests.Response with raise_for_status as no-op."""
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    if isinstance(payload, dict):
        mock.json.return_value = payload
    else:
        mock.text = payload
    return mock


def _error_resp(exc_class: type = requests.HTTPError) -> MagicMock:
    """Return a mock whose raise_for_status raises exc_class."""
    mock = MagicMock()
    mock.raise_for_status.side_effect = exc_class("error")
    return mock


# ---------------------------------------------------------------------------
# Tests: _parse_form4_xml (pure XML parser — no HTTP)
# ---------------------------------------------------------------------------


class TestParseForm4Xml:
    def test_parses_buy_transaction(self) -> None:
        trades = _parse_form4_xml(_FORM4_XML_BUY, "XOM")

        assert len(trades) == 1
        t = trades[0]
        assert t.instrument == "XOM"
        assert t.trade_type == "buy"
        assert t.trade_date == datetime(2024, 1, 15, tzinfo=UTC)
        assert t.shares == 500
        assert t.value_usd == pytest.approx(55_000.0)
        assert t.officer_name == "DOE JOHN"
        assert t.source == "edgar"

    def test_parses_sell_transaction(self) -> None:
        trades = _parse_form4_xml(_FORM4_XML_SELL, "XOM")

        assert len(trades) == 1
        assert trades[0].trade_type == "sell"

    def test_malformed_xml_returns_empty_and_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        with caplog.at_level(logging.WARNING):
            result = _parse_form4_xml("<<NOT VALID XML>>", "XOM")

        assert result == []
        assert any("parse error" in r.message.lower() for r in caplog.records)

    def test_unmapped_transaction_code_skipped(self) -> None:
        """Transaction code 'F' (tax withholding) is not in the map — silently skipped."""
        xml = _FORM4_XML_BUY.replace(
            "<transactionCode>P</transactionCode>",
            "<transactionCode>F</transactionCode>",
        )
        trades = _parse_form4_xml(xml, "XOM")
        assert trades == []

    def test_missing_officer_name_yields_none(self) -> None:
        xml = """<?xml version="1.0"?>
<ownershipDocument>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2024-01-15</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>100</value></transactionShares>
        <transactionPricePerShare><value>50.00</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""
        trades = _parse_form4_xml(xml, "CVX")
        assert len(trades) == 1
        assert trades[0].officer_name is None

    def test_invalid_date_skipped_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        xml = _FORM4_XML_BUY.replace(
            "<value>2024-01-15</value>",
            "<value>NOT-A-DATE</value>",
        )
        with caplog.at_level(logging.WARNING):
            trades = _parse_form4_xml(xml, "XOM")

        assert trades == []
        assert any("transactiondate" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# Tests: _efts_search (one HTTP call)
# ---------------------------------------------------------------------------


class TestEftsSearch:
    def test_returns_hits_list(self) -> None:
        with patch("requests.get", return_value=_mock_resp(_make_efts_response("XOM"))) as mock_get:
            hits = _efts_search("XOM", "2024-01-01")

        assert len(hits) == 1
        assert hits[0]["_id"] == "0001610717-24-000004"
        # Verify User-Agent header was sent
        _, kwargs = mock_get.call_args
        assert "User-Agent" in kwargs.get("headers", {})

    def test_empty_hits_returns_empty_list(self) -> None:
        empty = {"hits": {"hits": []}}
        with patch("requests.get", return_value=_mock_resp(empty)):
            hits = _efts_search("WTI", "2024-01-01")

        assert hits == []

    def test_http_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TENACITY_MAX_RETRIES", "1")
        with patch("requests.get", return_value=_error_resp(requests.HTTPError)):
            with pytest.raises(requests.HTTPError):
                _efts_search("XOM", "2024-01-01")


# ---------------------------------------------------------------------------
# Tests: fetch_edgar_insider_trades (full integration of helpers)
# ---------------------------------------------------------------------------


class TestFetchEdgarInsiderTrades:
    def _make_get_side_effect(
        self,
        efts_payload: dict,
        index_payload: dict,
        xml_text: str,
    ) -> list[MagicMock]:
        """Three sequential mock responses: EFTS → index → XML."""
        efts_resp = _mock_resp(efts_payload)
        index_resp = _mock_resp(index_payload)
        xml_resp = _mock_resp({})
        xml_resp.text = xml_text
        xml_resp.raise_for_status.return_value = None
        return [efts_resp, index_resp, xml_resp]

    def test_happy_path_returns_insider_trades(self) -> None:
        side_effects = self._make_get_side_effect(
            _make_efts_response("XOM"), _FILING_INDEX, _FORM4_XML_BUY
        )
        with patch("requests.get", side_effect=side_effects):
            trades = fetch_edgar_insider_trades(["XOM"])

        assert len(trades) == 1
        assert isinstance(trades[0], InsiderTrade)
        assert trades[0].instrument == "XOM"
        assert trades[0].trade_type == "buy"
        assert trades[0].shares == 500

    def test_empty_efts_returns_empty_list(self) -> None:
        empty_efts = {"hits": {"hits": []}}
        with patch("requests.get", return_value=_mock_resp(empty_efts)):
            trades = fetch_edgar_insider_trades(["WTI"])

        assert trades == []

    def test_only_requested_instruments_searched(self) -> None:
        """Verify EFTS is only called for the given tickers."""
        empty_efts = {"hits": {"hits": []}}
        with patch("requests.get", return_value=_mock_resp(empty_efts)) as mock_get:
            fetch_edgar_insider_trades(["XOM"])

        # Only one EFTS call for XOM — not for CVX, USO, etc.
        assert mock_get.call_count == 1
        call_url = mock_get.call_args[0][0]
        assert "efts.sec.gov" in call_url

    def test_malformed_xml_logs_warning_and_continues(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        efts_resp = _mock_resp(_make_efts_response("XOM"))
        index_resp = _mock_resp(_FILING_INDEX)
        xml_resp = MagicMock()
        xml_resp.raise_for_status.return_value = None
        xml_resp.text = "<<BROKEN XML>>"

        with patch("requests.get", side_effect=[efts_resp, index_resp, xml_resp]):
            with caplog.at_level(logging.WARNING):
                trades = fetch_edgar_insider_trades(["XOM"])

        assert trades == []

    def test_http_error_on_efts_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Network failure on EFTS search should propagate for tenacity to retry."""
        monkeypatch.setenv("TENACITY_MAX_RETRIES", "1")
        with patch(
            "requests.get",
            side_effect=requests.ConnectionError("timeout"),
        ):
            with pytest.raises(requests.ConnectionError):
                fetch_edgar_insider_trades(["XOM"])

    def test_multiple_instruments_all_searched(self) -> None:
        """Each instrument triggers its own EFTS call."""
        empty_efts = {"hits": {"hits": []}}
        with patch("requests.get", return_value=_mock_resp(empty_efts)) as mock_get:
            fetch_edgar_insider_trades(["XOM", "CVX", "USO"])

        # 3 EFTS calls, one per instrument
        assert mock_get.call_count == 3

    def test_no_xml_document_in_index_skips_filing(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        no_xml_index = {"directory": {"item": [{"name": "form4.htm", "type": "4"}]}}
        efts_resp = _mock_resp(_make_efts_response("CVX", cik="93410"))
        index_resp = _mock_resp(no_xml_index)

        with patch("requests.get", side_effect=[efts_resp, index_resp]):
            with caplog.at_level(logging.WARNING):
                trades = fetch_edgar_insider_trades(["CVX"])

        assert trades == []
        assert any("no xml" in r.message.lower() for r in caplog.records)
