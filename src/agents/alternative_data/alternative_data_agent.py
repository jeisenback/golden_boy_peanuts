"""
Alternative Data Agent — Phase 3 fetch functions.

Fetches alternative signals for the energy options opportunity agent:
  - fetch_edgar_insider_trades: SEC EDGAR Form 4 insider trade filings (issue #149)
  - fetch_reddit_sentiment: Reddit public JSON API narrative velocity (issue #151)
  - fetch_stocktwits_sentiment: Stocktwits symbol stream retail sentiment (issue #152)

ESOD constraints: @with_retry() on all external API calls, Pydantic boundary
models, type hints on all public functions, WARNING logs for missing/malformed
records, no silent failures.

EDGAR API notes:
  - Full-text search: https://efts.sec.gov/LATEST/search-index
  - Archives:         https://www.sec.gov/Archives/edgar/data
  - No API key required; User-Agent header mandatory (EDGAR Terms of Service).
  - WTI/BZ (crude futures) have no equity insider filings — returns empty list.

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
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Any
from xml.etree import ElementTree as ET

import requests

from src.agents.alternative_data.models import (
    EftsHit,
    EftsSearchResponse,
    FilingIndexResponse,
    InsiderTrade,
    NarrativeSignal,
    RedditPost,
    RedditSearchResponse,
    Sentiment,
)
from src.core.retry import with_retry

logger = logging.getLogger(__name__)

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
        except (ValueError, KeyError):
            logger.warning("fetch_edgar_insider_trades: EFTS search error for ticker=%s", ticker)
            continue

        for hit in hits:
            accession_no = hit.id
            raw_cik = hit.source.entity_id.lstrip("0")
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


def _efts_search(ticker: str, start_dt: str) -> list[EftsHit]:
    """
    Search EDGAR full-text search for Form 4 filings matching ticker.

    Args:
        ticker:   Ticker symbol (e.g. "XOM").
        start_dt: ISO date string (YYYY-MM-DD) for the lookback window start.

    Returns:
        Validated EFTS hit list (up to _MAX_HITS_PER_INSTRUMENT entries).

    Raises:
        requests.exceptions.RequestException: On HTTP or network failure.
        pydantic.ValidationError: If the EFTS response has an unexpected shape.
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
    return parsed.hits.hits[:_MAX_HITS_PER_INSTRUMENT]


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
    filing_index = FilingIndexResponse.model_validate(index_resp.json())

    xml_name: str | None = next(
        (item.name for item in filing_index.directory.item if item.name.endswith(".xml")),
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

        texts = [p.title + " " + p.selftext for p in posts]
        score = sum(p.score for p in posts)
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


def _reddit_search(instrument: str) -> list[RedditPost] | None:
    """
    Search Reddit for posts mentioning the instrument across target subreddits.

    Args:
        instrument: Ticker symbol to search for (e.g. "XOM").

    Returns:
        List of validated RedditPost objects on success; None if rate-limited (429).

    Raises:
        requests.exceptions.RequestException: On non-429 HTTP or network failure.
        pydantic.ValidationError: If the Reddit response has an unexpected shape.
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
    return [child.data for child in parsed.data.children]


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
