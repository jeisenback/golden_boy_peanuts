"""
Alternative Data Agent — Phase 3 fetch functions.

Fetches alternative signals for the energy options opportunity agent:
  - fetch_edgar_insider_trades: SEC EDGAR Form 4 insider trade filings (issue #149)
  - fetch_quiver_enrichment: Quiver Quantitative optional insider enrichment (issue #150)
  - fetch_reddit_sentiment: Reddit public JSON API narrative velocity (issue #151)
  - fetch_stocktwits_sentiment: Stocktwits symbol stream retail sentiment (issue #152)
  - fetch_tanker_flows: MarineTraffic chokepoint vessel events (issue #153)
  - run_alternative_data_ingestion: orchestrates all fetch functions above (issue #154)

ESOD constraints: @with_retry() on all external API calls, Pydantic boundary
models, type hints on all public functions, WARNING logs for missing/malformed
records, no silent failures.

EDGAR API notes:
  - Full-text search: https://efts.sec.gov/LATEST/search-index
  - Archives:         https://www.sec.gov/Archives/edgar/data
  - No API key required; User-Agent header mandatory (EDGAR Terms of Service).
  - WTI/BZ (crude futures) have no equity insider filings — returns empty list.

Quiver Quantitative API notes:
  - Endpoint: https://api.quiverquant.com/beta/live/insiders/{ticker}
  - Auth: Authorization: Token {QUIVER_API_KEY}
  - Optional enrichment — if QUIVER_API_KEY is absent, returns [] (graceful no-op).
  - HTTP errors logged as WARNING and swallowed; enrichment is best-effort.

Reddit API notes:
  - Public JSON API; no auth key required for read-only access.
  - Targets subreddits: r/energy, r/oil, r/investing (combined search).
  - Uses User-Agent header per Reddit API Terms of Service.
  - 429 responses logged as WARNING and return [] (not retried).

Stocktwits API notes:
  - Public symbol stream API; no auth key required for basic stream.
  - Endpoint: https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json
  - Message sentiment label "Bullish" → positive, "Bearish" → negative, absent → neutral.
  - 429 responses logged as WARNING and return [] (not retried).
  - Symbols with no stream data (404 or empty messages) logged as WARNING, return [].

MarineTraffic API notes:
  - Requires MARINETRAFFIC_API_KEY env var; absent → WARNING + return [].
  - Uses getVesselsInArea v:8 endpoint with lat/lon bounding boxes for each chokepoint.
  - Chokepoints: Strait of Hormuz, Suez Canal, Bosphorus (see _CHOKEPOINTS constant).
  - MMSI used as vessel_id; speed < threshold → "anchored", otherwise "transit".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import logging
import os
from typing import Any
from xml.etree import ElementTree as ET

from pydantic import ValidationError
import requests
from sqlalchemy.engine import Engine

from src.agents.alternative_data.db import (
    write_insider_trades,
    write_narrative_signal,
    write_shipping_events,
)
from src.agents.alternative_data.models import (
    AlternativeDataState,
    EftsSearchResponse,
    EventType,
    FilingIndexResponse,
    InsiderTrade,
    MarineTrafficVessel,
    NarrativeSignal,
    QuiverInsiderRow,
    RedditSearchResponse,
    Sentiment,
    ShippingEvent,
)
from src.core.db import get_engine
from src.core.retry import with_retry

logger = logging.getLogger(__name__)

# In-scope instrument universe for run_alternative_data_ingestion() (matches
# INSTRUMENTS_IN_SCOPE in strategy_evaluation_agent.py). WTI/BZ yield zero
# insider-trade hits (no equity filings) by design — see EDGAR notes above.
_INSTRUMENTS_IN_SCOPE: list[str] = ["USO", "XLE", "XOM", "CVX", "CL=F", "BZ=F"]

# Milliseconds per second — used to convert timedelta.total_seconds() to ms
# for the structured cycle log's duration_ms field
_MS_PER_SECOND: int = 1000

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EFTS_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

# EDGAR Terms of Service require a descriptive User-Agent
_USER_AGENT = "EnergyOptionsOpportunityAgent research@energy-options-agent.example"

# How many recent days to scan for Form 4 filings
_LOOKBACK_DAYS = 90

# Maximum EFTS hits to process per instrument (avoids runaway pagination)
_MAX_HITS_PER_INSTRUMENT = 10

# Form 4 transaction codes → trade_type values (matches DB CHECK constraint)
_TX_CODE_MAP: dict[str, str] = {
    "P": "buy",  # Open-market purchase
    "S": "sell",  # Open-market sale
    "A": "grant",  # Award / grant
    "M": "exercise",  # Option exercise
}

# ---------------------------------------------------------------------------
# Quiver Quantitative constants
# ---------------------------------------------------------------------------

_QUIVER_BASE_URL = "https://api.quiverquant.com"
_QUIVER_HTTP_TIMEOUT = 30  # seconds; consistent with EDGAR helpers above

# Quiver transaction labels → trade_type values
_QUIVER_TX_MAP: dict[str, str] = {
    "Buy": "buy",
    "Sale": "sell",
    "Award": "grant",
    "Option Exercise": "exercise",
}

# ---------------------------------------------------------------------------
# Public fetch function
# ---------------------------------------------------------------------------


@with_retry()
def fetch_edgar_insider_trades(instruments: list[str]) -> list[InsiderTrade]:
    """
    Fetch recent Form 4 insider trade filings for energy instruments.

    Searches SEC EDGAR full-text search API (free, no key required) for
    Form 4 filings mentioning each ticker. Downloads and parses the Form 4
    XML to extract trade details.

    Instruments with no equity insider filings (e.g. WTI crude futures)
    silently return zero records. Missing or malformed individual filings
    are logged as WARNING and skipped — the function never raises for
    per-filing errors.

    Args:
        instruments: Ticker symbols to search (e.g. ["XOM", "CVX", "USO", "XLE"]).

    Returns:
        List of InsiderTrade records across all instruments, ordered by
        instrument then most-recent-first as returned by EDGAR.

    Raises:
        requests.exceptions.RequestException: Propagated on network failure
            so tenacity can retry the full call.
    """
    all_trades: list[InsiderTrade] = []
    start_dt = (datetime.now(tz=UTC) - timedelta(days=_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    for ticker in instruments:
        try:
            hits = _efts_search(ticker, start_dt)
        except requests.exceptions.RequestException:
            raise  # let tenacity retry
        except ValidationError:
            raise  # malformed API response — let tenacity retry
        except (ValueError, KeyError):
            logger.warning("fetch_edgar_insider_trades: EFTS search error for ticker=%s", ticker)
            continue

        for hit in hits:
            accession_no: str = hit.get("_id", "")
            src: dict[str, Any] = hit.get("_source", {})
            # entity_id is zero-padded CIK (e.g. "0000034088"); strip leading zeros
            raw_cik = str(src.get("entity_id", "")).lstrip("0")
            if not accession_no or not raw_cik:
                logger.warning(
                    "fetch_edgar_insider_trades: missing accession_no or CIK in "
                    "EFTS hit for ticker=%s",
                    ticker,
                )
                continue

            try:
                xml_text = _fetch_form4_xml(raw_cik, accession_no)
            except requests.exceptions.RequestException:
                raise  # let tenacity retry
            except ValidationError:
                raise  # malformed API response — let tenacity retry
            except (ValueError, KeyError):
                logger.warning(
                    "fetch_edgar_insider_trades: failed to fetch XML for " "ticker=%s accession=%s",
                    ticker,
                    accession_no,
                )
                continue

            if xml_text is None:
                logger.warning(
                    "fetch_edgar_insider_trades: no XML document found for "
                    "ticker=%s accession=%s",
                    ticker,
                    accession_no,
                )
                continue

            # _parse_form4_xml handles ET.ParseError internally and returns [].
            # Unexpected exceptions propagate so the caller (tenacity) can retry.
            trades = _parse_form4_xml(xml_text, ticker)
            all_trades.extend(trades)

    return all_trades


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _efts_search(ticker: str, start_dt: str) -> list[dict[str, Any]]:
    """
    Search EDGAR full-text search for Form 4 filings matching ticker.

    Args:
        ticker:   Ticker symbol (e.g. "XOM").
        start_dt: ISO date string (YYYY-MM-DD) for the lookback window start.

    Returns:
        Raw EFTS hit list (up to _MAX_HITS_PER_INSTRUMENT entries).

    Raises:
        requests.exceptions.RequestException: On HTTP or network failure.
        pydantic.ValidationError: On malformed EFTS response shape.
    """
    resp = requests.get(
        _EFTS_SEARCH_URL,
        params={
            "q": f'"{ticker}"',
            "forms": "4",
            "dateRange": "custom",
            "startdt": start_dt,
        },
        headers={"User-Agent": _USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    parsed = EftsSearchResponse.model_validate(resp.json())
    hits: list[dict[str, Any]] = [
        {"_id": h.id, "_source": {"entity_id": h.source.entity_id}}
        for h in parsed.hits.hits[:_MAX_HITS_PER_INSTRUMENT]
    ]
    return hits


def _fetch_form4_xml(cik: str, accession_no: str) -> str | None:
    """
    Download Form 4 XML for a single EDGAR filing.

    Fetches the filing index JSON to discover the XML document filename,
    then downloads the XML document. Returns None if no .xml document
    is listed in the filing index.

    Args:
        cik:          CIK without leading zeros (e.g. "34088").
        accession_no: Hyphenated accession number (e.g. "0001610717-24-000004").

    Returns:
        XML text string, or None if no XML document found in the index.

    Raises:
        requests.exceptions.RequestException: On HTTP or network failure.
    """
    accession_nodash = accession_no.replace("-", "")
    index_url = f"{_ARCHIVES_BASE}/{cik}/{accession_nodash}/{accession_nodash}-index.json"

    index_resp = requests.get(index_url, headers={"User-Agent": _USER_AGENT}, timeout=30)
    index_resp.raise_for_status()
    parsed_index = FilingIndexResponse.model_validate(index_resp.json())

    xml_name: str | None = next(
        (item.name for item in parsed_index.directory.item if item.name.endswith(".xml")),
        None,
    )
    if xml_name is None:
        return None

    xml_url = f"{_ARCHIVES_BASE}/{cik}/{accession_nodash}/{xml_name}"
    xml_resp = requests.get(xml_url, headers={"User-Agent": _USER_AGENT}, timeout=30)
    xml_resp.raise_for_status()
    return xml_resp.text


def _parse_form4_xml(xml_text: str, instrument: str) -> list[InsiderTrade]:
    """
    Parse Form 4 XML into InsiderTrade records.

    Extracts nonDerivativeTransaction elements only. Transactions with
    unmapped transaction codes (e.g. "F" for tax withholding) are silently
    skipped. Malformed dates or amounts log a WARNING and skip the transaction.

    Args:
        xml_text:   Raw Form 4 XML string.
        instrument: Ticker symbol to attach to each InsiderTrade.

    Returns:
        List of InsiderTrade records. Empty list on parse error or no
        matching transactions.
    """
    try:
        root = ET.fromstring(xml_text)  # noqa: S314 — XML from SEC.gov (trusted source)
    except ET.ParseError as exc:
        logger.warning(
            "fetch_edgar_insider_trades: Form 4 XML parse error for %s: %s",
            instrument,
            exc,
        )
        return []

    officer_name: str | None = None
    owner_elem = root.find(".//reportingOwner/reportingOwnerId/rptOwnerName")
    if owner_elem is not None and owner_elem.text:
        officer_name = owner_elem.text.strip()

    trades: list[InsiderTrade] = []
    for tx in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        code_elem = tx.find(".//transactionCoding/transactionCode")
        date_elem = tx.find(".//transactionDate/value")

        if code_elem is None or date_elem is None:
            logger.warning(
                "fetch_edgar_insider_trades: missing code or date in Form 4 "
                "transaction for instrument=%s",
                instrument,
            )
            continue

        trade_type: str | None = _TX_CODE_MAP.get(code_elem.text or "")
        if trade_type is None:
            # Unknown/unsupported transaction code (F, J, etc.) — skip silently
            continue

        try:
            trade_date = datetime.strptime((date_elem.text or "").strip(), "%Y-%m-%d").replace(
                tzinfo=UTC
            )
        except ValueError:
            logger.warning(
                "fetch_edgar_insider_trades: invalid transactionDate %r for " "instrument=%s",
                date_elem.text,
                instrument,
            )
            continue

        shares: int | None = None
        shares_elem = tx.find(".//transactionAmounts/transactionShares/value")
        if shares_elem is not None and shares_elem.text:
            try:
                shares = int(float(shares_elem.text))
            except ValueError:
                pass

        value_usd: float | None = None
        price_elem = tx.find(".//transactionAmounts/transactionPricePerShare/value")
        if shares is not None and price_elem is not None and price_elem.text:
            try:
                value_usd = round(shares * float(price_elem.text), 2)
            except ValueError:
                pass

        trades.append(
            InsiderTrade(
                instrument=instrument,
                trade_date=trade_date,
                trade_type=trade_type,
                shares=shares,
                value_usd=value_usd,
                officer_name=officer_name,
                source="edgar",
            )
        )

    return trades


# ---------------------------------------------------------------------------
# Quiver Quantitative fetch function
# ---------------------------------------------------------------------------


@with_retry()
def fetch_quiver_enrichment(instruments: list[str]) -> list[InsiderTrade]:
    """
    Optionally enrich insider trade data via Quiver Quantitative API.

    Returns an empty list and logs INFO if ``QUIVER_API_KEY`` is not set.
    HTTP errors are logged as WARNING and swallowed — this is best-effort
    optional enrichment; a Quiver outage must not block the pipeline.

    Args:
        instruments: Ticker symbols to enrich (e.g. ["XOM", "CVX"]).

    Returns:
        List of InsiderTrade records with ``source="quiver"``, or ``[]``
        if the API key is absent or all requests fail.
    """
    api_key = os.environ.get("QUIVER_API_KEY", "").strip()
    if not api_key:
        logger.info("fetch_quiver_enrichment: QUIVER_API_KEY not set — skipping enrichment")
        return []

    all_trades: list[InsiderTrade] = []
    for ticker in instruments:
        trades = _fetch_quiver_ticker(ticker, api_key)
        all_trades.extend(trades)
    return all_trades


def _fetch_quiver_ticker(ticker: str, api_key: str) -> list[InsiderTrade]:
    """
    Fetch insider trades for a single ticker from Quiver Quantitative.

    HTTP errors (4xx/5xx) are logged as WARNING and return ``[]`` — a bad
    ticker or auth failure must not abort the enrichment pass. Transient
    network errors (timeout, connection refused) are re-raised so the
    ``@with_retry()`` on ``fetch_quiver_enrichment`` can retry them.

    Args:
        ticker:  Ticker symbol (e.g. "XOM").
        api_key: Quiver Quantitative API key.

    Returns:
        List of InsiderTrade records for the ticker, or ``[]`` on HTTP failure.

    Raises:
        requests.exceptions.RequestException: On transient network failure,
            propagated so tenacity can retry the full enrichment call.
    """
    url = f"{_QUIVER_BASE_URL}/beta/live/insiders/{ticker}"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Token {api_key}"},
            timeout=_QUIVER_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        # HTTP 4xx/5xx: log and degrade gracefully — retrying won't help
        logger.warning("fetch_quiver_enrichment: HTTP error for ticker=%s: %s", ticker, exc)
        return []
    # Network-level errors (Timeout, ConnectionError, etc.) propagate to tenacity

    raw_response = resp.json()
    if not isinstance(raw_response, list):
        logger.warning(
            "fetch_quiver_enrichment: unexpected response shape for ticker=%s (not a list)",
            ticker,
        )
        return []

    trades: list[InsiderTrade] = []
    for raw_row in raw_response:
        try:
            validated_row = QuiverInsiderRow.model_validate(raw_row)
        except Exception as exc:  # Pydantic ValidationError is broad — catch-all intentional
            logger.warning(
                "fetch_quiver_enrichment: row validation failed for ticker=%s: %s", ticker, exc
            )
            continue
        trade = _parse_quiver_row(validated_row, ticker)
        if trade is not None:
            trades.append(trade)
    return trades


def _parse_quiver_row(row: QuiverInsiderRow, instrument: str) -> InsiderTrade | None:
    """
    Parse a validated ``QuiverInsiderRow`` into an ``InsiderTrade``.

    Rows with unmapped transaction types or unparseable dates are
    logged as WARNING and return None.

    Args:
        row:        Validated ``QuiverInsiderRow`` from the API response.
        instrument: Ticker symbol to attach to the record.

    Returns:
        InsiderTrade on success, None if the row should be skipped.
    """
    raw_type = str(row.Transaction or "")
    trade_type = _QUIVER_TX_MAP.get(raw_type)
    if trade_type is None:
        logger.warning(
            "fetch_quiver_enrichment: unmapped transaction type %r for ticker=%s — skipping",
            raw_type,
            instrument,
        )
        return None

    raw_date = str(row.Date or "").strip()
    try:
        trade_date = datetime.strptime(raw_date, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        logger.warning(
            "fetch_quiver_enrichment: unparseable date %r for ticker=%s — skipping",
            raw_date,
            instrument,
        )
        return None

    shares: int | None = int(row.Shares) if row.Shares is not None else None
    value_usd: float | None = (
        round(shares * row.Price, 2) if shares is not None and row.Price is not None else None
    )

    return InsiderTrade(
        instrument=instrument,
        trade_date=trade_date,
        trade_type=trade_type,
        shares=shares,
        value_usd=value_usd,
        officer_name=str(row.Name or "").strip() or None,
        source="quiver",
    )


# ===========================================================================
# fetch_reddit_sentiment — issue #151
# ===========================================================================

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REDDIT_SUBREDDITS = "energy+oil+investing"
_REDDIT_SEARCH_URL = "https://www.reddit.com/r/{subreddits}/search.json"

# Reddit API Terms of Service require a descriptive User-Agent
_REDDIT_USER_AGENT = (
    "EnergyOptionsOpportunityAgent/1.0 (research; contact: research@energy-options-agent.example)"
)

# How many days back the sliding window covers (matches Reddit "t=week")
_REDDIT_LOOKBACK_DAYS = 7

# Maximum posts requested per instrument per subreddit group
_REDDIT_POST_LIMIT = 100

# Request timeout in seconds for Reddit API calls
_REDDIT_TIMEOUT = 30

# Reddit time-filter value for the search API — must match _REDDIT_LOOKBACK_DAYS = 7
_REDDIT_TIME_FILTER = "week"

# Keywords used for positive/negative sentiment classification heuristic.
# Sets allow O(1) membership tests during classification.
_POSITIVE_KEYWORDS: frozenset[str] = frozenset(
    [
        "bullish",
        "rally",
        "surge",
        "buy",
        "long",
        "strong",
        "gain",
        "profit",
        "upside",
        "recovery",
        "boom",
        "high",
    ]
)
_NEGATIVE_KEYWORDS: frozenset[str] = frozenset(
    [
        "bearish",
        "crash",
        "fall",
        "drop",
        "sell",
        "short",
        "weak",
        "loss",
        "decline",
        "risk",
        "bust",
        "low",
    ]
)

# ---------------------------------------------------------------------------
# Public fetch function
# ---------------------------------------------------------------------------


@with_retry()
def fetch_reddit_sentiment(instruments: list[str]) -> list[NarrativeSignal]:
    """
    Fetch Reddit narrative velocity for energy instruments.

    Searches r/energy, r/oil, and r/investing for posts mentioning each
    instrument. Aggregates net upvote score and mention count, then
    classifies sentiment via a keyword heuristic on post titles and body
    text. Uses the Reddit public JSON API (no auth key required).

    A 429 rate-limit response is logged as WARNING and causes the function
    to return [] immediately without retrying (rate limits affect all
    subsequent calls in the same window).

    Args:
        instruments: Ticker symbols to search (e.g. ["XOM", "CVX", "USO"]).

    Returns:
        List of NarrativeSignal records, one per instrument that has at
        least one matching post. Instruments with zero posts are omitted.
        Returns [] on rate-limit (429).

    Raises:
        requests.exceptions.RequestException: Propagated on network failure
            so tenacity can retry the full call.
    """
    window_end = datetime.now(tz=UTC)
    window_start = window_end - timedelta(days=_REDDIT_LOOKBACK_DAYS)

    results: list[NarrativeSignal] = []

    for instrument in instruments:
        posts = _reddit_search(instrument)
        if posts is None:
            # Rate limited — log already emitted by _reddit_search; bail early
            return []
        if not posts:
            continue

        texts = [p.get("title", "") + " " + p.get("selftext", "") for p in posts]
        score = sum(p.get("score", 0) for p in posts)
        sentiment = _classify_sentiment(texts)

        results.append(
            NarrativeSignal(
                instrument=instrument,
                platform="reddit",
                score=score,
                mention_count=len(posts),
                sentiment=sentiment,
                window_start=window_start,
                window_end=window_end,
                source="reddit",
            )
        )

    return results


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _reddit_search(instrument: str) -> list[dict[str, Any]] | None:
    """
    Search Reddit for posts mentioning the instrument across target subreddits.

    Args:
        instrument: Ticker symbol to search for (e.g. "XOM").

    Returns:
        List of post data dicts on success; None if rate-limited (429).

    Raises:
        requests.exceptions.RequestException: On non-429 HTTP or network failure.
        pydantic.ValidationError: On malformed Reddit response shape.
    """
    resp = requests.get(
        _REDDIT_SEARCH_URL.format(subreddits=_REDDIT_SUBREDDITS),
        params={
            "q": instrument,
            "sort": "new",
            "restrict_sr": "1",
            "limit": str(_REDDIT_POST_LIMIT),
            "t": _REDDIT_TIME_FILTER,
        },
        headers={"User-Agent": _REDDIT_USER_AGENT},
        timeout=_REDDIT_TIMEOUT,
    )

    if resp.status_code == 429:
        logger.warning("fetch_reddit_sentiment: rate limited (429) for instrument=%s", instrument)
        return None

    resp.raise_for_status()
    parsed = RedditSearchResponse.model_validate(resp.json())
    return [
        {"title": child.data.title, "selftext": child.data.selftext, "score": child.data.score}
        for child in parsed.data.children
    ]


def _classify_sentiment(texts: list[str]) -> Sentiment:
    """
    Classify aggregate sentiment from a list of post text strings.

    Counts occurrences of positive and negative keywords across all
    texts (case-insensitive word-boundary match). Returns Sentiment.POSITIVE
    if positive keyword hits exceed negative, Sentiment.NEGATIVE if the reverse,
    and Sentiment.NEUTRAL when counts are equal or both are zero.

    Args:
        texts: List of strings (post title + body) to classify.

    Returns:
        Sentiment enum value: POSITIVE, NEUTRAL, or NEGATIVE.
    """
    combined = " ".join(texts).lower()
    words = set(combined.split())
    pos_hits = len(words & _POSITIVE_KEYWORDS)
    neg_hits = len(words & _NEGATIVE_KEYWORDS)

    if pos_hits > neg_hits:
        return Sentiment.POSITIVE
    if neg_hits > pos_hits:
        return Sentiment.NEGATIVE
    return Sentiment.NEUTRAL


# ===========================================================================
# fetch_stocktwits_sentiment — issue #152
# ===========================================================================

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STOCKTWITS_STREAM_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"

# Request timeout in seconds for Stocktwits API calls
_STOCKTWITS_TIMEOUT = 30

# Stocktwits sentiment label → Sentiment enum mapping
_STOCKTWITS_SENTIMENT_MAP: dict[str, Sentiment] = {
    "Bullish": Sentiment.POSITIVE,
    "Bearish": Sentiment.NEGATIVE,
}

# ---------------------------------------------------------------------------
# Public fetch function
# ---------------------------------------------------------------------------


@with_retry()
def fetch_stocktwits_sentiment(instruments: list[str]) -> list[NarrativeSignal]:
    """
    Fetch Stocktwits retail sentiment for energy instruments.

    Calls the Stocktwits public symbol stream API for each instrument and
    aggregates message count and Bullish/Bearish label distribution into a
    NarrativeSignal. No API key required for the public stream.

    Sentiment is derived from label counts: more Bullish labels → positive,
    more Bearish → negative, equal or no labels → neutral.

    A 429 rate-limit response is logged as WARNING and returns [] immediately.
    A missing symbol (404) or empty stream is logged as WARNING and the
    instrument is skipped.

    Args:
        instruments: Ticker symbols to query (e.g. ["XOM", "CVX", "USO"]).

    Returns:
        List of NarrativeSignal records, one per instrument with at least one
        message. Instruments with no messages are omitted.
        Returns [] on rate-limit (429).

    Raises:
        requests.exceptions.RequestException: Propagated on non-429/404
            network failure so tenacity can retry.
    """
    window_end = datetime.now(tz=UTC)
    window_start = window_end - timedelta(days=1)  # Stocktwits stream is ~24h

    results: list[NarrativeSignal] = []

    for instrument in instruments:
        messages = _stocktwits_stream(instrument)
        if messages is None:
            # Rate limited — bail early; log already emitted by helper
            return []
        if not messages:
            continue

        bullish = sum(
            1
            for m in messages
            if m.get("entities", {}).get("sentiment", {}) is not None
            and (m.get("entities", {}).get("sentiment") or {}).get("basic") == "Bullish"
        )
        bearish = sum(
            1
            for m in messages
            if m.get("entities", {}).get("sentiment", {}) is not None
            and (m.get("entities", {}).get("sentiment") or {}).get("basic") == "Bearish"
        )

        if bullish > bearish:
            sentiment = Sentiment.POSITIVE
        elif bearish > bullish:
            sentiment = Sentiment.NEGATIVE
        else:
            sentiment = Sentiment.NEUTRAL

        # score = net bullish minus bearish (can be negative)
        score = bullish - bearish

        results.append(
            NarrativeSignal(
                instrument=instrument,
                platform="stocktwits",
                score=score,
                mention_count=len(messages),
                sentiment=sentiment,
                window_start=window_start,
                window_end=window_end,
                source="stocktwits",
            )
        )

    return results


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------


def _stocktwits_stream(instrument: str) -> list[dict[str, Any]] | None:
    """
    Fetch the Stocktwits public symbol stream for one instrument.

    Args:
        instrument: Ticker symbol (e.g. "XOM").

    Returns:
        List of message dicts on success; None if rate-limited (429);
        empty list [] if symbol not found (404) or stream is empty.

    Raises:
        requests.exceptions.RequestException: On non-429/404 HTTP or
            network failure.
    """
    resp = requests.get(
        _STOCKTWITS_STREAM_URL.format(symbol=instrument),
        timeout=_STOCKTWITS_TIMEOUT,
    )

    if resp.status_code == 429:
        logger.warning(
            "fetch_stocktwits_sentiment: rate limited (429) for instrument=%s", instrument
        )
        return None

    if resp.status_code == 404:
        logger.warning(
            "fetch_stocktwits_sentiment: symbol not found (404) for instrument=%s", instrument
        )
        return []

    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    messages: list[dict[str, Any]] = data.get("messages", [])

    if not messages:
        logger.warning("fetch_stocktwits_sentiment: empty stream for instrument=%s", instrument)

    return messages


# ===========================================================================
# fetch_tanker_flows — issue #153
# ===========================================================================

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MARINETRAFFIC_API_URL = (
    "https://services.marinetraffic.com/api/getVesselsInArea/v:8"
    "/{api_key}"
    "/MINLAT:{minlat}/MAXLAT:{maxlat}/MINLON:{minlon}/MAXLON:{maxlon}"
    "/TIMESPAN:{timespan}/msgtype:json"
)

# Request timeout in seconds for MarineTraffic API calls
_MARINETRAFFIC_TIMEOUT = 30

# How many minutes back to scan for vessel positions
_MARINETRAFFIC_TIMESPAN_MINUTES = 60

# Vessels with speed (knots) at or below this threshold are classified "anchored"
_ANCHORED_SPEED_THRESHOLD = 0.5

# Named chokepoint bounding boxes — (minlat, maxlat, minlon, maxlon)
# Each entry is: (name, minlat, maxlat, minlon, maxlon)
_CHOKEPOINTS: list[tuple[str, float, float, float, float]] = [
    ("strait_of_hormuz", 25.5, 27.0, 55.5, 57.5),
    ("suez_canal", 29.5, 31.5, 32.0, 33.5),
    ("bosphorus", 41.0, 41.5, 28.5, 29.5),
]


# ---------------------------------------------------------------------------
# Public fetch function
# ---------------------------------------------------------------------------


@with_retry()
def fetch_tanker_flows() -> list[ShippingEvent]:
    """
    Fetch vessel positions at key energy supply chokepoints.

    Queries the MarineTraffic getVesselsInArea API for each chokepoint
    bounding box and classifies vessels as "transit" or "anchored" based
    on reported speed. Returns [] and logs a WARNING when
    MARINETRAFFIC_API_KEY is absent.

    Args:
        None — scans all three configured chokepoints unconditionally.

    Returns:
        List of ShippingEvent records across all chokepoints.
        Returns [] if MARINETRAFFIC_API_KEY env var is not set.

    Raises:
        requests.exceptions.RequestException: Propagated on network failure
            so tenacity can retry the full call.
    """
    api_key = os.environ.get("MARINETRAFFIC_API_KEY", "")
    if not api_key:
        logger.warning(
            "fetch_tanker_flows: MARINETRAFFIC_API_KEY not set — skipping tanker flow fetch"
        )
        return []

    fetched_at = datetime.now(tz=UTC)
    all_events: list[ShippingEvent] = []

    for name, minlat, maxlat, minlon, maxlon in _CHOKEPOINTS:
        try:
            vessels = _fetch_vessels_in_area(api_key, minlat, maxlat, minlon, maxlon)
        except requests.exceptions.RequestException:
            raise  # let tenacity retry
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "fetch_tanker_flows: failed to fetch vessels for chokepoint=%s: %s", name, exc
            )
            continue

        for vessel in vessels:
            try:
                event = _vessel_to_shipping_event(vessel, fetched_at)
            except (ValueError, KeyError, TypeError) as exc:
                logger.warning(
                    "fetch_tanker_flows: skipping malformed vessel record " "at chokepoint=%s: %s",
                    name,
                    exc,
                )
                continue
            all_events.append(event)

    return all_events


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _redact_api_key(message: str, api_key: str) -> str:
    """Replace any occurrence of the raw API key in an error message with '***'."""
    return message.replace(api_key, "***") if api_key else message


def _fetch_vessels_in_area(
    api_key: str,
    minlat: float,
    maxlat: float,
    minlon: float,
    maxlon: float,
) -> list[MarineTrafficVessel]:
    """
    Call MarineTraffic getVesselsInArea for a single bounding box.

    Args:
        api_key: MarineTraffic API key.
        minlat: Southern latitude boundary.
        maxlat: Northern latitude boundary.
        minlon: Western longitude boundary.
        maxlon: Eastern longitude boundary.

    Returns:
        List of vessel records validated against MarineTrafficVessel.
        Individual malformed rows are logged as WARNING and skipped.

    Raises:
        requests.exceptions.RequestException: On HTTP or network failure.
            The API key is redacted from the exception message before it
            propagates, since MarineTraffic embeds it in the request URL
            and this exception is otherwise logged verbatim by tenacity's
            before_sleep hook.
    """
    url = _MARINETRAFFIC_API_URL.format(
        api_key=api_key,
        minlat=minlat,
        maxlat=maxlat,
        minlon=minlon,
        maxlon=maxlon,
        timespan=_MARINETRAFFIC_TIMESPAN_MINUTES,
    )
    try:
        resp = requests.get(url, timeout=_MARINETRAFFIC_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise type(exc)(_redact_api_key(str(exc), api_key)) from exc

    data: list[dict[str, Any]] | dict[str, Any] = resp.json()
    # MarineTraffic v8 returns a list directly or {"DATA": [...]}
    raw_vessels: list[dict[str, Any]] = (
        data if isinstance(data, list) else list(data.get("DATA", []))
    )

    vessels: list[MarineTrafficVessel] = []
    for raw in raw_vessels:
        try:
            vessels.append(MarineTrafficVessel.model_validate(raw))
        except ValidationError as exc:
            logger.warning("fetch_tanker_flows: skipping malformed vessel record: %s", exc)
            continue
    return vessels


def _vessel_to_shipping_event(
    vessel: MarineTrafficVessel,
    fetched_at: datetime,
) -> ShippingEvent:
    """
    Convert a validated MarineTraffic vessel record into a ShippingEvent.

    Vessels with SPEED <= _ANCHORED_SPEED_THRESHOLD knots are classified
    as "anchored"; all others as "transit".

    Args:
        vessel:     Validated MarineTrafficVessel from _fetch_vessels_in_area.
        fetched_at: UTC timestamp when the batch was fetched.

    Returns:
        ShippingEvent with validated fields.
    """
    event_type = (
        EventType.ANCHORED if vessel.SPEED <= _ANCHORED_SPEED_THRESHOLD else EventType.TRANSIT
    )

    # TIMESTAMP field (UTC epoch seconds) is optional — fall back to fetched_at
    if vessel.TIMESTAMP is not None:
        try:
            timestamp = datetime.fromtimestamp(vessel.TIMESTAMP, tz=UTC)
        except (ValueError, OSError):
            timestamp = fetched_at
    else:
        timestamp = fetched_at

    return ShippingEvent(
        vessel_id=vessel.MMSI,
        event_type=event_type,
        latitude=vessel.LAT,
        longitude=vessel.LON,
        timestamp=timestamp,
        source="marinetraffic",
    )


# ===========================================================================
# run_alternative_data_ingestion — issue #154
# ===========================================================================


def run_alternative_data_ingestion() -> AlternativeDataState:
    """
    Execute one full alternative-data ingestion cycle.

    Calls fetch_edgar_insider_trades(), fetch_quiver_enrichment(),
    fetch_reddit_sentiment(), fetch_stocktwits_sentiment(), and
    fetch_tanker_flows() in independent try/except blocks so one feed
    failure does not abort the others. Persists all successfully fetched
    records to PostgreSQL; DB write failures are also caught and recorded
    rather than propagated.

    Emits a structured JSON log at cycle end with insider_trade_records,
    narrative_signal_records, shipping_event_records, error_count, and
    duration_ms.

    Returns:
        AlternativeDataState with insider_trades, narrative_signals,
        shipping_events, and alternative_data_errors populated.
        alternative_data_errors is the ESOD-4 structured error response:
        callers MUST inspect it to distinguish feed failures from DB
        outages. An empty list indicates a fully successful cycle.
        Never raises — even total feed failure returns an empty-but-valid
        state.
    """
    start_time = datetime.now(tz=UTC)
    insider_trades: list[InsiderTrade] = []
    narrative_signals: list[NarrativeSignal] = []
    shipping_events: list[ShippingEvent] = []
    errors: list[str] = []

    # --- Fetch feeds (each isolated so one failure cannot abort the others) ---
    try:
        insider_trades.extend(fetch_edgar_insider_trades(_INSTRUMENTS_IN_SCOPE))
    except Exception as exc:
        logger.exception("fetch_edgar_insider_trades failed")
        errors.append(f"fetch_edgar_insider_trades: {exc}")

    try:
        insider_trades.extend(fetch_quiver_enrichment(_INSTRUMENTS_IN_SCOPE))
    except Exception as exc:
        logger.exception("fetch_quiver_enrichment failed")
        errors.append(f"fetch_quiver_enrichment: {exc}")

    try:
        narrative_signals.extend(fetch_reddit_sentiment(_INSTRUMENTS_IN_SCOPE))
    except Exception as exc:
        logger.exception("fetch_reddit_sentiment failed")
        errors.append(f"fetch_reddit_sentiment: {exc}")

    try:
        narrative_signals.extend(fetch_stocktwits_sentiment(_INSTRUMENTS_IN_SCOPE))
    except Exception as exc:
        logger.exception("fetch_stocktwits_sentiment failed")
        errors.append(f"fetch_stocktwits_sentiment: {exc}")

    try:
        shipping_events.extend(fetch_tanker_flows())
    except Exception as exc:
        logger.exception("fetch_tanker_flows failed")
        errors.append(f"fetch_tanker_flows: {exc}")

    # --- Persist to PostgreSQL ---
    _engine: Engine | None = None
    try:
        _engine = get_engine()
    except Exception as exc:
        logger.exception("Failed to acquire DB engine — skipping persistence")
        errors.append(f"get_engine: {exc}")

    if _engine is not None and insider_trades:
        try:
            write_insider_trades(insider_trades, _engine)
        except Exception as exc:
            logger.exception("write_insider_trades failed; insider trade records not persisted")
            errors.append(f"write_insider_trades: {exc}")

    if _engine is not None and shipping_events:
        try:
            write_shipping_events(shipping_events, _engine)
        except Exception as exc:
            logger.exception("write_shipping_events failed; shipping event records not persisted")
            errors.append(f"write_shipping_events: {exc}")

    if _engine is not None and narrative_signals:
        for signal in narrative_signals:
            try:
                write_narrative_signal(signal, _engine)
            except Exception as exc:
                logger.exception(
                    "write_narrative_signal failed for instrument=%s platform=%s",
                    signal.instrument,
                    signal.platform,
                )
                errors.append(f"write_narrative_signal: {exc}")

    # --- Assemble AlternativeDataState ---
    snapshot_time = datetime.now(tz=UTC)
    state = AlternativeDataState(
        snapshot_time=snapshot_time,
        insider_trades=insider_trades,
        narrative_signals=narrative_signals,
        shipping_events=shipping_events,
        alternative_data_errors=errors,
    )

    # --- Structured cycle log ---
    duration_ms = int((snapshot_time - start_time).total_seconds() * _MS_PER_SECOND)
    logger.info(
        json.dumps(
            {
                "event": "alternative_data_ingestion_cycle_complete",
                "insider_trade_records": len(insider_trades),
                "narrative_signal_records": len(narrative_signals),
                "shipping_event_records": len(shipping_events),
                "error_count": len(errors),
                "duration_ms": duration_ms,
            }
        )
    )

    return state
