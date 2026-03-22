"""
Alternative Data Agent — Phase 3 fetch functions.

Fetches alternative signals for the energy options opportunity agent:
  - fetch_edgar_insider_trades: SEC EDGAR Form 4 insider trade filings (issue #149)

ESOD constraints: @with_retry() on all external API calls, Pydantic boundary
models, type hints on all public functions, WARNING logs for missing/malformed
records, no silent failures.

EDGAR API notes:
  - Full-text search: https://efts.sec.gov/LATEST/search-index
  - Archives:         https://www.sec.gov/Archives/edgar/data
  - No API key required; User-Agent header mandatory (EDGAR Terms of Service).
  - WTI/BZ (crude futures) have no equity insider filings — returns empty list.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Any
from xml.etree import ElementTree as ET

import requests

from src.agents.alternative_data.models import InsiderTrade
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
        except Exception:
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
            except Exception:
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

            try:
                trades = _parse_form4_xml(xml_text, ticker)
                all_trades.extend(trades)
            except Exception:
                logger.warning(
                    "fetch_edgar_insider_trades: failed to parse Form 4 XML for "
                    "ticker=%s accession=%s",
                    ticker,
                    accession_no,
                )

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
