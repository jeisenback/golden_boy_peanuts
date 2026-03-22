"""
Alternative Data Agent — Phase 3 fetch functions.

Fetches alternative signals for the energy options opportunity agent:
  - fetch_edgar_insider_trades: SEC EDGAR Form 4 insider trade filings (issue #149)
  - fetch_reddit_sentiment: Reddit public JSON API narrative velocity (issue #151)

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
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Any
from xml.etree import ElementTree as ET

import requests

from src.agents.alternative_data.models import InsiderTrade, NarrativeSignal
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
    data: dict[str, Any] = resp.json()
    hits: list[dict[str, Any]] = data.get("hits", {}).get("hits", [])
    return hits[:_MAX_HITS_PER_INSTRUMENT]


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
    index_data: dict[str, Any] = index_resp.json()

    items: list[dict[str, Any]] = index_data.get("directory", {}).get("item", [])
    xml_name: str | None = next(
        (item["name"] for item in items if item.get("name", "").endswith(".xml")),
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
    """
    resp = requests.get(
        _REDDIT_SEARCH_URL.format(subreddits=_REDDIT_SUBREDDITS),
        params={
            "q": instrument,
            "sort": "new",
            "restrict_sr": "1",
            "limit": str(_REDDIT_POST_LIMIT),
            "t": "week",
        },
        headers={"User-Agent": _REDDIT_USER_AGENT},
        timeout=_REDDIT_TIMEOUT,
    )

    if resp.status_code == 429:
        logger.warning("fetch_reddit_sentiment: rate limited (429) for instrument=%s", instrument)
        return None

    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    children: list[dict[str, Any]] = data.get("data", {}).get("children", [])
    return [child.get("data", {}) for child in children]


def _classify_sentiment(texts: list[str]) -> str:
    """
    Classify aggregate sentiment from a list of post text strings.

    Counts occurrences of positive and negative keywords across all
    texts (case-insensitive word-boundary match). Returns "positive"
    if positive keyword hits exceed negative, "negative" if the reverse,
    and "neutral" when counts are equal or both are zero.

    Args:
        texts: List of strings (post title + body) to classify.

    Returns:
        One of "positive", "neutral", or "negative".
    """
    combined = " ".join(texts).lower()
    words = set(combined.split())
    pos_hits = len(words & _POSITIVE_KEYWORDS)
    neg_hits = len(words & _NEGATIVE_KEYWORDS)

    if pos_hits > neg_hits:
        return "positive"
    if neg_hits > pos_hits:
        return "negative"
    return "neutral"
