"""
Unit tests for alternative_data_agent (issues #149, #150).

Tests use mocked HTTP responses — no real API calls.
Integration tests (real network) belong in a separate integration test file.

Coverage (EDGAR #149):
  - Happy path: EFTS hit → XML fetch → parse → InsiderTrade records returned
  - Malformed XML: parse error logged as WARNING, empty list returned
  - Empty EFTS result: no hits, empty list returned
  - HTTP error propagates: RequestException raised for tenacity retry
  - Instrument filter: only specified instruments searched
  - Unmapped transaction code: skipped silently (no InsiderTrade for "F")
  - Missing officer name: officer_name=None allowed

Coverage (Quiver #150):
  - No API key: logs INFO, returns [] (graceful no-op)
  - Happy path: API response → InsiderTrade records with source="quiver"
  - HTTP error: logged as WARNING, returns [] (not raised)
  - Empty response: returns []
  - Unmapped transaction type: skipped with WARNING
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

from pydantic import ValidationError
import pytest
import requests

from src.agents.alternative_data.alternative_data_agent import (
    _efts_search,
    _parse_form4_xml,
    fetch_edgar_insider_trades,
    fetch_quiver_enrichment,
)
from src.agents.alternative_data.models import (
    EftsSearchResponse,
    FilingIndexResponse,
    InsiderTrade,
    RedditSearchResponse,
)

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


def _mock_resp(payload: dict | str, status: int = 200, status_code: int | None = None) -> MagicMock:
    """Return a mock requests.Response with raise_for_status as no-op."""
    mock = MagicMock()
    mock.status_code = status_code if status_code is not None else status
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
# Tests: Pydantic boundary models — malformed API responses (issue #183)
# ---------------------------------------------------------------------------


class TestEftsBoundaryModelValidation:
    """Malformed EFTS responses must raise pydantic.ValidationError (#183)."""

    def test_malformed_efts_missing_source_raises(self) -> None:
        """EFTS hit without _source object raises ValidationError."""
        bad_payload = {"hits": {"hits": [{"_id": "0001610717-24-000004"}]}}
        with pytest.raises(ValidationError):
            EftsSearchResponse.model_validate(bad_payload)

    def test_malformed_efts_wrong_type_raises(self) -> None:
        """EFTS hits as a string (not an object) raises ValidationError."""
        bad_payload = {"hits": "not-an-object"}
        with pytest.raises(ValidationError):
            EftsSearchResponse.model_validate(bad_payload)

    def test_efts_valid_response_round_trips(self) -> None:
        """Valid EFTS response parses correctly through model."""
        payload = _make_efts_response("XOM")
        parsed = EftsSearchResponse.model_validate(payload)
        assert len(parsed.hits.hits) == 1
        assert parsed.hits.hits[0].id == "0001610717-24-000004"
        assert parsed.hits.hits[0].source.entity_id == "0000034088"

    def test_missing_top_level_hits_raises(self) -> None:
        """EFTS response missing 'hits' key entirely raises ValidationError."""
        with pytest.raises(ValidationError):
            EftsSearchResponse.model_validate({"total": 0})

    def test_malformed_efts_propagates_from_efts_search(self) -> None:
        """_efts_search raises ValidationError on malformed EFTS JSON."""
        bad_payload = {"hits": {"hits": [{"_id": "123"}]}}
        with patch("requests.get", return_value=_mock_resp(bad_payload)):
            with pytest.raises(ValidationError):
                _efts_search("XOM", "2024-01-01")

    def test_validation_error_propagates_through_fetch_edgar(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ValidationError from _efts_search is NOT swallowed by fetch_edgar_insider_trades."""
        monkeypatch.setenv("TENACITY_MAX_RETRIES", "1")
        bad_payload = {"hits": {"hits": [{"_id": "123"}]}}
        with patch("requests.get", return_value=_mock_resp(bad_payload)):
            with pytest.raises(ValidationError):
                fetch_edgar_insider_trades(["XOM"])


class TestFilingIndexBoundaryModelValidation:
    """Malformed filing index responses must raise pydantic.ValidationError (#183)."""

    def test_malformed_index_directory_wrong_type_raises(self) -> None:
        """Filing index with directory as a list (not an object) raises ValidationError."""
        bad_payload = {"directory": ["not", "an", "object"]}
        with pytest.raises(ValidationError):
            FilingIndexResponse.model_validate(bad_payload)

    def test_missing_top_level_directory_raises(self) -> None:
        """Filing index missing 'directory' key entirely raises ValidationError."""
        with pytest.raises(ValidationError):
            FilingIndexResponse.model_validate({"name": "index.json"})

    def test_valid_index_round_trips(self) -> None:
        """Valid filing index parses correctly through model."""
        parsed = FilingIndexResponse.model_validate(_FILING_INDEX)
        assert len(parsed.directory.item) == 2
        assert parsed.directory.item[0].name == "wf-form4_20240117.xml"


class TestRedditBoundaryModelValidation:
    """Malformed Reddit responses must raise pydantic.ValidationError (#183)."""

    def test_malformed_reddit_missing_title_raises(self) -> None:
        """Reddit post without required 'title' field raises ValidationError."""
        bad_payload = {"data": {"children": [{"data": {"selftext": "no title here"}}]}}
        with pytest.raises(ValidationError):
            RedditSearchResponse.model_validate(bad_payload)

    def test_malformed_reddit_wrong_structure_raises(self) -> None:
        """Reddit response with data as a string raises ValidationError."""
        bad_payload = {"data": "not-an-object"}
        with pytest.raises(ValidationError):
            RedditSearchResponse.model_validate(bad_payload)

    def test_reddit_valid_response_round_trips(self) -> None:
        """Valid Reddit response parses correctly through model."""
        payload = _make_reddit_response([_make_post("XOM rally", "big move", 42)])
        parsed = RedditSearchResponse.model_validate(payload)
        assert len(parsed.data.children) == 1
        assert parsed.data.children[0].data.title == "XOM rally"
        assert parsed.data.children[0].data.selftext == "big move"
        assert parsed.data.children[0].data.score == 42

    def test_missing_top_level_data_raises(self) -> None:
        """Reddit response missing 'data' key entirely raises ValidationError."""
        with pytest.raises(ValidationError):
            RedditSearchResponse.model_validate({"kind": "Listing"})

    def test_malformed_reddit_propagates_from_reddit_search(self) -> None:
        """_reddit_search raises ValidationError on malformed Reddit JSON."""
        from src.agents.alternative_data.alternative_data_agent import _reddit_search

        bad_payload = {"data": {"children": [{"data": {}}]}}
        with patch("requests.get", return_value=_mock_resp(bad_payload)):
            with pytest.raises(ValidationError):
                _reddit_search("XOM")


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
        assert urlparse(call_url).netloc == "efts.sec.gov"

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


# ---------------------------------------------------------------------------
# fetch_quiver_enrichment tests (issue #150)
# ---------------------------------------------------------------------------


def _quiver_row(
    ticker: str = "XOM",
    transaction: str = "Buy",
    date: str = "2024-06-01",
    shares: int = 5000,
    price: float = 110.00,
    name: str = "Jane Smith",
) -> dict:
    """Minimal Quiver API response row."""
    return {
        "Transaction": transaction,
        "Date": date,
        "Shares": shares,
        "Price": price,
        "Name": name,
    }


class TestFetchQuiverEnrichment:
    def test_no_api_key_returns_empty_list_and_logs_info(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If QUIVER_API_KEY is absent, return [] and log INFO — no HTTP call made."""
        import logging

        monkeypatch.delenv("QUIVER_API_KEY", raising=False)

        with patch("requests.get") as mock_get:
            with caplog.at_level(logging.INFO):
                result = fetch_quiver_enrichment(["XOM", "CVX"])

        assert result == []
        mock_get.assert_not_called()
        assert any("quiver_api_key not set" in r.message.lower() for r in caplog.records)

    def test_happy_path_returns_insider_trade_records(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Valid API response produces InsiderTrade records with source='quiver'."""
        monkeypatch.setenv("QUIVER_API_KEY", "test-key-123")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = [
            _quiver_row("XOM", "Buy", "2024-06-01", 5000, 110.00, "Jane Smith"),
            _quiver_row("XOM", "Sale", "2024-05-15", 2000, 108.50, "Bob Jones"),
        ]

        with patch("requests.get", return_value=mock_resp):
            result = fetch_quiver_enrichment(["XOM"])

        assert len(result) == 2
        buy = result[0]
        assert isinstance(buy, InsiderTrade)
        assert buy.instrument == "XOM"
        assert buy.trade_type == "buy"
        assert buy.source == "quiver"
        assert buy.shares == 5000
        assert buy.value_usd == round(5000 * 110.00, 2)
        assert buy.officer_name == "Jane Smith"
        assert buy.trade_date == datetime(2024, 6, 1, tzinfo=UTC)

        sell = result[1]
        assert sell.trade_type == "sell"
        assert sell.shares == 2000

    def test_http_error_logged_as_warning_not_raised(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """HTTP errors are swallowed (logged WARNING, return []) — pipeline must not break."""
        import logging

        monkeypatch.setenv("QUIVER_API_KEY", "test-key-123")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("403 Forbidden")

        with patch("requests.get", return_value=mock_resp):
            with caplog.at_level(logging.WARNING):
                result = fetch_quiver_enrichment(["XOM"])

        assert result == []
        assert any("http error" in r.message.lower() for r in caplog.records)

    def test_empty_response_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty API response list returns [] without error."""
        monkeypatch.setenv("QUIVER_API_KEY", "test-key-123")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = []

        with patch("requests.get", return_value=mock_resp):
            result = fetch_quiver_enrichment(["CVX"])

        assert result == []

    def test_unmapped_transaction_type_skipped_with_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Rows with unmapped transaction types are skipped and logged as WARNING."""
        import logging

        monkeypatch.setenv("QUIVER_API_KEY", "test-key-123")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = [
            _quiver_row("XOM", "Unknown Disposition", "2024-06-01"),
        ]

        with patch("requests.get", return_value=mock_resp):
            with caplog.at_level(logging.WARNING):
                result = fetch_quiver_enrichment(["XOM"])

        assert result == []
        assert any("unmapped transaction type" in r.message.lower() for r in caplog.records)

    def test_network_error_propagates_for_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Transient network errors propagate so @with_retry() can retry them."""
        monkeypatch.setenv("QUIVER_API_KEY", "test-key-123")
        monkeypatch.setenv("TENACITY_MAX_RETRIES", "1")

        with patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("connection refused"),
        ):
            with pytest.raises(requests.exceptions.ConnectionError):
                fetch_quiver_enrichment(["XOM"])

    def test_non_list_response_returns_empty_list_with_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If the API returns a dict instead of a list, log WARNING and return []."""
        import logging

        monkeypatch.setenv("QUIVER_API_KEY", "test-key-123")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"error": "unexpected shape"}

        with patch("requests.get", return_value=mock_resp):
            with caplog.at_level(logging.WARNING):
                result = fetch_quiver_enrichment(["XOM"])

        assert result == []
        assert any("unexpected response shape" in r.message.lower() for r in caplog.records)


# ===========================================================================
# fetch_reddit_sentiment tests — issue #151
# ===========================================================================

from src.agents.alternative_data.alternative_data_agent import (  # noqa: E402
    _classify_sentiment,
    fetch_reddit_sentiment,
)
from src.agents.alternative_data.models import NarrativeSignal  # noqa: E402

_REDDIT_SEARCH_URL = "https://www.reddit.com/r/energy+oil+investing/search.json"


def _make_reddit_response(posts: list[dict]) -> dict:
    """Minimal Reddit search JSON envelope."""
    return {
        "data": {
            "children": [{"data": p} for p in posts],
        }
    }


def _make_post(title: str = "XOM rally", selftext: str = "", score: int = 10) -> dict:
    return {"title": title, "selftext": selftext, "score": score}


class TestFetchRedditSentimentHappyPath:
    def test_returns_narrative_signal_for_matching_instrument(self) -> None:
        posts = [_make_post("XOM surges on strong earnings", score=50)]
        resp = _mock_resp(_make_reddit_response(posts))

        with patch("requests.get", return_value=resp):
            signals = fetch_reddit_sentiment(["XOM"])

        assert len(signals) == 1
        sig = signals[0]
        assert isinstance(sig, NarrativeSignal)
        assert sig.instrument == "XOM"
        assert sig.platform == "reddit"
        assert sig.source == "reddit"
        assert sig.score == 50
        assert sig.mention_count == 1

    def test_score_is_sum_of_post_scores(self) -> None:
        posts = [_make_post(score=20), _make_post(score=30), _make_post(score=5)]
        resp = _mock_resp(_make_reddit_response(posts))

        with patch("requests.get", return_value=resp):
            signals = fetch_reddit_sentiment(["CVX"])

        assert signals[0].score == 55
        assert signals[0].mention_count == 3

    def test_window_start_and_end_are_set(self) -> None:
        from datetime import UTC, datetime, timedelta

        posts = [_make_post()]
        resp = _mock_resp(_make_reddit_response(posts))

        before = datetime.now(tz=UTC)
        with patch("requests.get", return_value=resp):
            signals = fetch_reddit_sentiment(["XOM"])
        after = datetime.now(tz=UTC)

        sig = signals[0]
        assert before - timedelta(seconds=1) <= sig.window_end <= after
        expected_start = sig.window_end - timedelta(days=7)
        # Allow 1-second tolerance
        assert abs((sig.window_start - expected_start).total_seconds()) < 2


class TestFetchRedditSentimentNoMentions:
    def test_no_posts_returns_empty_list(self) -> None:
        resp = _mock_resp(_make_reddit_response([]))

        with patch("requests.get", return_value=resp):
            signals = fetch_reddit_sentiment(["WTI"])

        assert signals == []

    def test_instrument_omitted_when_no_posts(self) -> None:
        empty = _mock_resp(_make_reddit_response([]))
        with_posts = _mock_resp(_make_reddit_response([_make_post("CVX buy")]))

        with patch("requests.get", side_effect=[empty, with_posts]):
            signals = fetch_reddit_sentiment(["XOM", "CVX"])

        assert len(signals) == 1
        assert signals[0].instrument == "CVX"


class TestFetchRedditSentiment429:
    def test_rate_limit_returns_empty_list(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        rate_limited = _mock_resp({}, status=429)

        with patch("requests.get", return_value=rate_limited):
            with caplog.at_level(logging.WARNING):
                signals = fetch_reddit_sentiment(["XOM"])

        assert signals == []
        assert any("429" in r.message or "rate limit" in r.message.lower() for r in caplog.records)

    def test_rate_limit_mid_batch_returns_empty(self) -> None:
        """If second instrument gets 429, whole function returns []."""
        first_ok = _mock_resp(_make_reddit_response([_make_post()]))
        rate_limited = _mock_resp({}, status=429)

        with patch("requests.get", side_effect=[first_ok, rate_limited]):
            signals = fetch_reddit_sentiment(["XOM", "CVX"])

        assert signals == []


class TestClassifySentiment:
    def test_positive_keywords_yield_positive(self) -> None:
        assert _classify_sentiment(["XOM bullish rally surge"]) == "positive"

    def test_negative_keywords_yield_negative(self) -> None:
        assert _classify_sentiment(["oil crash bearish drop"]) == "negative"

    def test_neutral_when_balanced(self) -> None:
        assert _classify_sentiment(["bullish crash"]) == "neutral"

    def test_neutral_when_no_keywords(self) -> None:
        assert _classify_sentiment(["XOM quarterly earnings report"]) == "neutral"

    def test_case_insensitive(self) -> None:
        assert _classify_sentiment(["BULLISH RALLY SURGE"]) == "positive"


# ===========================================================================
# fetch_stocktwits_sentiment tests — issue #152
# ===========================================================================

from src.agents.alternative_data.alternative_data_agent import (  # noqa: E402
    fetch_stocktwits_sentiment,
)

_STOCKTWITS_URL_TEMPLATE = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"


def _make_stocktwits_response(messages: list[dict]) -> dict:
    """Minimal Stocktwits symbol stream JSON envelope."""
    return {"messages": messages}


def _make_message(sentiment_label: str | None = None, body: str = "XOM looks good") -> dict:
    """Build a minimal Stocktwits message dict."""
    entities: dict = {}
    if sentiment_label is not None:
        entities["sentiment"] = {"basic": sentiment_label}
    else:
        entities["sentiment"] = None
    return {"body": body, "entities": entities}


class TestFetchStocktwitsHappyPath:
    def test_bullish_messages_return_positive_signal(self) -> None:
        messages = [_make_message("Bullish"), _make_message("Bullish"), _make_message("Bearish")]
        resp = _mock_resp(_make_stocktwits_response(messages))

        with patch("requests.get", return_value=resp):
            signals = fetch_stocktwits_sentiment(["XOM"])

        assert len(signals) == 1
        sig = signals[0]
        assert isinstance(sig, NarrativeSignal)
        assert sig.instrument == "XOM"
        assert sig.platform == "stocktwits"
        assert sig.source == "stocktwits"
        assert sig.sentiment == "positive"
        assert sig.score == 1  # 2 bullish - 1 bearish
        assert sig.mention_count == 3

    def test_bearish_majority_returns_negative_signal(self) -> None:
        messages = [_make_message("Bearish"), _make_message("Bearish"), _make_message("Bullish")]
        resp = _mock_resp(_make_stocktwits_response(messages))

        with patch("requests.get", return_value=resp):
            signals = fetch_stocktwits_sentiment(["CVX"])

        assert signals[0].sentiment == "negative"
        assert signals[0].score == -1

    def test_equal_bullish_bearish_returns_neutral(self) -> None:
        messages = [_make_message("Bullish"), _make_message("Bearish")]
        resp = _mock_resp(_make_stocktwits_response(messages))

        with patch("requests.get", return_value=resp):
            signals = fetch_stocktwits_sentiment(["USO"])

        assert signals[0].sentiment == "neutral"
        assert signals[0].score == 0

    def test_unlabeled_messages_return_neutral(self) -> None:
        messages = [_make_message(None), _make_message(None)]
        resp = _mock_resp(_make_stocktwits_response(messages))

        with patch("requests.get", return_value=resp):
            signals = fetch_stocktwits_sentiment(["XLE"])

        assert signals[0].sentiment == "neutral"
        assert signals[0].mention_count == 2

    def test_multi_instrument_aggregated_independently(self) -> None:
        bullish_resp = _mock_resp(_make_stocktwits_response([_make_message("Bullish")]))
        bearish_resp = _mock_resp(_make_stocktwits_response([_make_message("Bearish")]))

        with patch("requests.get", side_effect=[bullish_resp, bearish_resp]):
            signals = fetch_stocktwits_sentiment(["XOM", "CVX"])

        assert len(signals) == 2
        assert signals[0].instrument == "XOM"
        assert signals[0].sentiment == "positive"
        assert signals[1].instrument == "CVX"
        assert signals[1].sentiment == "negative"


class TestFetchStocktwitsEmptyStream:
    def test_empty_messages_skips_instrument(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        resp = _mock_resp(_make_stocktwits_response([]))

        with patch("requests.get", return_value=resp):
            with caplog.at_level(logging.WARNING):
                signals = fetch_stocktwits_sentiment(["WTI"])

        assert signals == []
        assert any("empty stream" in r.message.lower() for r in caplog.records)

    def test_404_skips_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        not_found = _mock_resp({}, status=404)

        with patch("requests.get", return_value=not_found):
            with caplog.at_level(logging.WARNING):
                signals = fetch_stocktwits_sentiment(["WTI"])

        assert signals == []
        assert any("404" in r.message or "not found" in r.message.lower() for r in caplog.records)


class TestFetchStocktwits429:
    def test_rate_limit_returns_empty_list(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        rate_limited = _mock_resp({}, status=429)

        with patch("requests.get", return_value=rate_limited):
            with caplog.at_level(logging.WARNING):
                signals = fetch_stocktwits_sentiment(["XOM"])

        assert signals == []
        assert any("429" in r.message or "rate limit" in r.message.lower() for r in caplog.records)

    def test_rate_limit_mid_batch_returns_empty(self) -> None:
        first_ok = _mock_resp(_make_stocktwits_response([_make_message("Bullish")]))
        rate_limited = _mock_resp({}, status=429)

        with patch("requests.get", side_effect=[first_ok, rate_limited]):
            signals = fetch_stocktwits_sentiment(["XOM", "CVX"])

        assert signals == []


class TestFetchStocktwitsHttpError:
    def test_non_429_http_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TENACITY_MAX_RETRIES", "1")
        with patch("requests.get", side_effect=requests.ConnectionError("timeout")):
            with pytest.raises(requests.ConnectionError):
                fetch_stocktwits_sentiment(["XOM"])


# ===========================================================================
# fetch_tanker_flows tests — issue #153
# ===========================================================================

from src.agents.alternative_data.alternative_data_agent import (  # noqa: E402
    _vessel_to_shipping_event,
    fetch_tanker_flows,
)
from src.agents.alternative_data.models import (  # noqa: E402
    EventType,
    MarineTrafficVessel,
    ShippingEvent,
)

_MARINETRAFFIC_URL_PREFIX = "https://services.marinetraffic.com/api/getVesselsInArea"


def _make_vessel(
    mmsi: str = "123456789",
    lat: float = 26.5,
    lon: float = 56.5,
    speed: float = 5.0,
    timestamp: int | None = None,
) -> dict:
    v: dict = {"MMSI": mmsi, "LAT": str(lat), "LON": str(lon), "SPEED": str(speed)}
    if timestamp is not None:
        v["TIMESTAMP"] = str(timestamp)
    return v


def _mt_resp(vessels: list[dict]) -> MagicMock:
    """Mock MarineTraffic response returning vessel list directly."""
    mock = MagicMock()
    mock.status_code = 200
    mock.raise_for_status.return_value = None
    mock.json.return_value = vessels
    return mock


class TestFetchTankerFlowsNoKey:
    def test_missing_api_key_returns_empty_and_warns(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        monkeypatch.delenv("MARINETRAFFIC_API_KEY", raising=False)
        with caplog.at_level(logging.WARNING):
            events = fetch_tanker_flows()

        assert events == []
        assert any("marinetraffic_api_key" in r.message.lower() for r in caplog.records)


class TestFetchTankerFlowsHappyPath:
    def test_transit_vessel_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MARINETRAFFIC_API_KEY", "test-key")
        vessel = _make_vessel(mmsi="111111111", lat=26.5, lon=56.5, speed=8.0)
        # 3 chokepoints → 3 API calls; return vessel only on first, empty on others
        resps = [_mt_resp([vessel]), _mt_resp([]), _mt_resp([])]

        with patch("requests.get", side_effect=resps):
            events = fetch_tanker_flows()

        assert len(events) == 1
        e = events[0]
        assert isinstance(e, ShippingEvent)
        assert e.vessel_id == "111111111"
        assert e.event_type == EventType.TRANSIT
        assert e.latitude == pytest.approx(26.5)
        assert e.longitude == pytest.approx(56.5)
        assert e.source == "marinetraffic"

    def test_anchored_vessel_below_speed_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MARINETRAFFIC_API_KEY", "test-key")
        vessel = _make_vessel(speed=0.2)
        resps = [_mt_resp([vessel]), _mt_resp([]), _mt_resp([])]

        with patch("requests.get", side_effect=resps):
            events = fetch_tanker_flows()

        assert events[0].event_type == EventType.ANCHORED

    def test_speed_at_threshold_is_anchored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MARINETRAFFIC_API_KEY", "test-key")
        vessel = _make_vessel(speed=0.5)  # exactly at threshold
        resps = [_mt_resp([vessel]), _mt_resp([]), _mt_resp([])]

        with patch("requests.get", side_effect=resps):
            events = fetch_tanker_flows()

        assert events[0].event_type == EventType.ANCHORED

    def test_all_three_chokepoints_queried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MARINETRAFFIC_API_KEY", "test-key")
        resps = [_mt_resp([_make_vessel()]), _mt_resp([_make_vessel("222")]), _mt_resp([])]

        with patch("requests.get", side_effect=resps) as mock_get:
            events = fetch_tanker_flows()

        assert mock_get.call_count == 3
        assert len(events) == 2

    def test_dict_envelope_response_handled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MarineTraffic v8 may return {'DATA': [...]} instead of a bare list."""
        monkeypatch.setenv("MARINETRAFFIC_API_KEY", "test-key")
        envelope = {"DATA": [_make_vessel()]}
        resps = [_mock_resp(envelope), _mt_resp([]), _mt_resp([])]

        with patch("requests.get", side_effect=resps):
            events = fetch_tanker_flows()

        assert len(events) == 1


class TestFetchTankerFlowsEmptyResponse:
    def test_empty_vessel_list_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MARINETRAFFIC_API_KEY", "test-key")
        resps = [_mt_resp([]), _mt_resp([]), _mt_resp([])]

        with patch("requests.get", side_effect=resps):
            events = fetch_tanker_flows()

        assert events == []


class TestFetchTankerFlowsMalformedVessel:
    def test_missing_mmsi_skips_with_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        monkeypatch.setenv("MARINETRAFFIC_API_KEY", "test-key")
        bad_vessel = {"LAT": "26.5", "LON": "56.5", "SPEED": "5.0"}  # no MMSI
        resps = [_mt_resp([bad_vessel]), _mt_resp([]), _mt_resp([])]

        with patch("requests.get", side_effect=resps):
            with caplog.at_level(logging.WARNING):
                events = fetch_tanker_flows()

        assert events == []
        assert any("malformed" in r.message.lower() for r in caplog.records)

    def test_non_numeric_lat_skips_with_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """MarineTrafficVessel boundary validation rejects unparseable LAT (ESOD-1)."""
        import logging

        monkeypatch.setenv("MARINETRAFFIC_API_KEY", "test-key")
        bad_vessel = {"MMSI": "123456789", "LAT": "not-a-number", "LON": "56.5", "SPEED": "5.0"}
        resps = [_mt_resp([bad_vessel]), _mt_resp([]), _mt_resp([])]

        with patch("requests.get", side_effect=resps):
            with caplog.at_level(logging.WARNING):
                events = fetch_tanker_flows()

        assert events == []
        assert any("malformed" in r.message.lower() for r in caplog.records)


class TestFetchTankerFlowsHttpError:
    def test_http_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MARINETRAFFIC_API_KEY", "test-key")
        monkeypatch.setenv("TENACITY_MAX_RETRIES", "1")

        with patch("requests.get", side_effect=requests.ConnectionError("timeout")):
            with pytest.raises(requests.ConnectionError):
                fetch_tanker_flows()

    def test_api_key_redacted_from_propagated_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """API key in the request URL must never reach logs via the propagated exception."""
        monkeypatch.setenv("MARINETRAFFIC_API_KEY", "super-secret-key")
        monkeypatch.setenv("TENACITY_MAX_RETRIES", "1")

        url_with_key = (
            "https://services.marinetraffic.com/api/getVesselsInArea/v:8"
            "/super-secret-key/MINLAT:25.5/MAXLAT:27.0/MINLON:55.5/MAXLON:57.5"
        )
        error = requests.exceptions.HTTPError(
            f"404 Client Error: Not Found for url: {url_with_key}"
        )

        with patch("requests.get", side_effect=error):
            with pytest.raises(requests.exceptions.HTTPError) as excinfo:
                fetch_tanker_flows()

        assert "super-secret-key" not in str(excinfo.value)
        assert "***" in str(excinfo.value)


class TestVesselToShippingEvent:
    def test_timestamp_field_parsed(self) -> None:
        from datetime import UTC, datetime

        vessel = MarineTrafficVessel.model_validate(_make_vessel(timestamp=1700000000))
        fetched_at = datetime.now(tz=UTC)
        event = _vessel_to_shipping_event(vessel, fetched_at)

        assert event.timestamp == datetime.fromtimestamp(1700000000, tz=UTC)

    def test_missing_timestamp_falls_back_to_fetched_at(self) -> None:
        from datetime import UTC, datetime

        vessel = MarineTrafficVessel.model_validate(_make_vessel())  # no timestamp
        fetched_at = datetime(2024, 1, 15, 12, 0, tzinfo=UTC)
        event = _vessel_to_shipping_event(vessel, fetched_at)

        assert event.timestamp == fetched_at
