"""
Event Detection Agent

Responsibilities (Design Doc Section 4, PRD Section 4.2):
  - Monitor news and geopolitical feeds (GDELT, NewsAPI)
  - Identify supply disruptions, refinery outages, tanker chokepoints,
    and geopolitical events relevant to energy markets
  - Assign confidence scores and intensity levels to each detected event
  - Persist events to PostgreSQL for use by Feature Generation Agent

ESOD constraints: Python 3.11+, type hints on all public functions,
no langchain.*/langgraph.* imports, tenacity on all external API calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import logging
import os

from pydantic import ValidationError
import requests

from src.agents.event_detection.db import write_detected_events, write_eia_records
from src.agents.event_detection.models import (
    ClassifyLLMResponse,
    DetectedEvent,
    EIAInventoryRecord,
    EventIntensity,
    EventType,
)
from src.core.db import get_engine
from src.core.llm_wrapper import LLMWrapper
from src.core.retry import with_retry

logger = logging.getLogger(__name__)


class EventDetectionError(RuntimeError):
    """Raised by run_event_detection() on unrecoverable failure.

    Allows pipeline.py to catch event detection failures without depending
    on the underlying HTTP library (requests, httpx, etc.).
    """


_HTTP_TIMEOUT_SECONDS: int = 10

# NewsAPI query for energy market relevance
_NEWSAPI_QUERY: str = "crude oil OR WTI OR Brent OR energy supply OR OPEC"
_NEWSAPI_BASE_URL: str = "https://newsapi.org/v2/everything"
_NEWSAPI_PAGE_SIZE: int = 20

# GDELT Doc API v2 query and parameters
_GDELT_QUERY: str = "crude oil supply disruption OR OPEC OR refinery"
_GDELT_MAX_RECORDS: int = 20
_GDELT_TIMESPAN_MINUTES: int = 1440  # 24 hours

# EIA API v2 endpoints and fetch parameters
_EIA_CRUDE_STOCKS_PATH: str = "/v2/petroleum/sum/sndw/data/"
_EIA_REFINERY_UTIL_PATH: str = "/v2/petroleum/pnp/wiup/data/"
_EIA_FETCH_WEEKS: int = 4  # most recent 4 weeks per fetch

# LLM model for event classification — Haiku for speed and cost efficiency
_CLASSIFY_MODEL_ID: str = "claude-haiku-4-5-20251001"
_CLASSIFY_MAX_TOKENS: int = 256

# Prompt template for LLM event classification (kept ≤ 500 tokens)
_CLASSIFY_PROMPT_TEMPLATE: str = """\
You are an energy market analyst. Classify the following news article.

Title: {title}
Source: {source}
Published: {published_at}
Description: {description}

Respond with a JSON object only — no preamble, no markdown:
{{
  "is_relevant": true or false,
  "event_type": one of ["supply_disruption","refinery_outage","tanker_chokepoint",\
"geopolitical","sanctions","unknown"],
  "confidence_score": float between 0.0 and 1.0,
  "intensity": one of ["low","medium","high"],
  "description": "one-sentence summary of the event",
  "affected_instruments": list of ticker strings from ["USO","XLE","XOM","CVX","CL=F","BZ=F"] or []
}}

Set is_relevant to false if the article is not about energy markets, supply, or geopolitics\
 affecting oil prices.
"""


@with_retry()
def fetch_news_events() -> list[dict[str, object]]:
    """
    Fetch recent energy-related article metadata from NewsAPI.

    Queries the NewsAPI /v2/everything endpoint for articles matching
    energy/commodity keywords published in the last 24 hours. Returns
    raw article dicts for downstream classification by classify_event().

    If NEWSAPI_KEY is not set, logs a WARNING and returns [] (degraded mode).

    Returns:
        List of raw article dicts with at minimum: title, description,
        source (dict with name key), publishedAt, url. Empty list if the
        key is absent or the response contains no articles.

    Raises:
        requests.HTTPError: Propagates after all retry attempts if the
            API returns a non-2xx status code.
    """
    api_key = os.environ.get("NEWSAPI_KEY")
    if not api_key:
        logger.warning("NEWSAPI_KEY not set; skipping NewsAPI fetch (degraded mode)")
        return []

    from_dt = (datetime.now(tz=UTC) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")

    params: dict[str, str | int] = {
        "q": _NEWSAPI_QUERY,
        "sortBy": "publishedAt",
        "pageSize": _NEWSAPI_PAGE_SIZE,
        "language": "en",
        "from": from_dt,
        "apiKey": api_key,
    }
    response = requests.get(
        _NEWSAPI_BASE_URL,
        params=params,
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data: dict[str, object] = response.json()

    raw: object = data.get("articles", [])
    articles: list[dict[str, object]] = raw if isinstance(raw, list) else []
    logger.info("fetch_news_events: retrieved %d article(s) from NewsAPI", len(articles))
    return articles


@with_retry()
def fetch_gdelt_events() -> list[dict[str, object]]:
    """
    Fetch recent energy-related articles from the GDELT Project Doc API v2.

    Free tier, no API key required. Queries for energy/commodity disruption
    keywords over the past 24 hours. Returns raw article dicts for downstream
    classification by classify_event().

    Falls back to the default GDELT URL if GDELT_BASE_URL is not set.

    Returns:
        List of raw article dicts with at minimum: title, url, seendate
        (normalized to ISO 8601 UTC), domain. Empty list if the response
        contains no articles.

    Raises:
        requests.HTTPError: Propagates after all retry attempts if the
            API returns a non-2xx status code.
    """
    base_url = os.environ.get("GDELT_BASE_URL", "http://api.gdeltproject.org/api/v2")

    gdelt_params: dict[str, str | int] = {
        "query": _GDELT_QUERY,
        "mode": "artlist",
        "maxrecords": _GDELT_MAX_RECORDS,
        "format": "json",
        "timespan": _GDELT_TIMESPAN_MINUTES,
    }
    response = requests.get(
        f"{base_url}/doc/doc",
        params=gdelt_params,
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data: dict[str, object] = response.json()

    raw_gdelt: object = data.get("articles", [])
    raw_articles: list[dict[str, object]] = raw_gdelt if isinstance(raw_gdelt, list) else []
    if not raw_articles:
        logger.info("fetch_gdelt_events: no articles returned from GDELT")
        return []

    # Normalize seendate (YYYYMMDDTHHMMSSZ) to ISO 8601 for consistent handling
    articles: list[dict[str, object]] = []
    for article in raw_articles:
        seendate_raw = article.get("seendate", "")
        seendate: str = seendate_raw if isinstance(seendate_raw, str) else ""
        try:
            dt = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            normalized_seendate: str = dt.isoformat()
        except (ValueError, TypeError):
            logger.warning(
                "fetch_gdelt_events: unparseable seendate %r for url=%r; using raw value",
                seendate,
                article.get("url", ""),
            )
            normalized_seendate = seendate
        articles.append(
            {
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "seendate": normalized_seendate,
                "publishedAt": normalized_seendate,  # unified key for classify_event
                "domain": article.get("domain", ""),
                "source": {"name": article.get("domain", "gdelt")},
            }
        )

    logger.info("fetch_gdelt_events: retrieved %d article(s) from GDELT", len(articles))
    return articles


def _fetch_eia_series(
    base_url: str,
    api_key: str,
    path: str,
) -> dict[str, float | None]:
    """
    Fetch one EIA API v2 data series and return a period → value mapping.

    Args:
        base_url: EIA API base URL (e.g. https://api.eia.gov).
        api_key: EIA API key.
        path: Series path (e.g. /v2/petroleum/sum/sndw/data/).

    Returns:
        Dict mapping period string (YYYY-WW) to float value or None if
        the EIA record has a null value for that period.

    Raises:
        requests.HTTPError: Propagates on non-2xx response.
    """
    params: dict[str, str | int] = {
        "api_key": api_key,
        "frequency": "weekly",
        "data[0]": "value",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": _EIA_FETCH_WEEKS,
    }
    response = requests.get(
        f"{base_url}{path}",
        params=params,
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data: dict[str, object] = response.json()

    raw_inner: object = data.get("response", {})
    inner: dict[str, object] = raw_inner if isinstance(raw_inner, dict) else {}
    raw_records: object = inner.get("data", [])
    records: list[dict[str, object]] = raw_records if isinstance(raw_records, list) else []

    result: dict[str, float | None] = {}
    for record in records:
        period_raw = record.get("period", "")
        period: str = period_raw if isinstance(period_raw, str) else ""
        if not period:
            continue
        raw_value = record.get("value")
        value: float | None = None
        if raw_value is not None:
            try:
                value = float(raw_value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                logger.warning(
                    "_fetch_eia_series: unparseable value %r for period=%r in %s",
                    raw_value,
                    period,
                    path,
                )
        result[period] = value
    return result


@with_retry()
def fetch_eia_data() -> list[EIAInventoryRecord]:
    """
    Fetch weekly EIA petroleum inventory data for the most recent 4 weeks.

    Queries two EIA API v2 series:
      - /v2/petroleum/sum/sndw/data/ : U.S. crude oil stocks (millions of barrels)
      - /v2/petroleum/pnp/wiup/data/ : U.S. refinery utilization rate (percent)

    Records from both series are merged by period and returned as a list of
    EIAInventoryRecord objects sorted newest-first.

    If EIA_API_KEY is not set, logs a WARNING and returns [] (degraded mode).
    Override the base URL for testing via the EIA_BASE_URL env var.

    Returns:
        List of EIAInventoryRecord, one per reporting period, newest first.
        Empty list if the API key is absent or both series return no data.

    Raises:
        requests.HTTPError: Propagates after all retry attempts if either
            series endpoint returns a non-2xx status.
    """
    api_key = os.environ.get("EIA_API_KEY")
    if not api_key:
        logger.warning("EIA_API_KEY not set; skipping EIA fetch (degraded mode)")
        return []

    base_url = os.environ.get("EIA_BASE_URL", "https://api.eia.gov")
    fetched_at = datetime.now(tz=UTC)

    crude_by_period = _fetch_eia_series(base_url, api_key, _EIA_CRUDE_STOCKS_PATH)
    refinery_by_period = _fetch_eia_series(base_url, api_key, _EIA_REFINERY_UTIL_PATH)

    all_periods: set[str] = set(crude_by_period) | set(refinery_by_period)
    records: list[EIAInventoryRecord] = []
    for period in all_periods:
        try:
            record = EIAInventoryRecord(
                period=period,
                crude_stocks_mb=crude_by_period.get(period),
                refinery_utilization_pct=refinery_by_period.get(period),
                fetched_at=fetched_at,
            )
            records.append(record)
        except Exception:
            logger.warning(
                "fetch_eia_data: skipping malformed record for period=%r",
                period,
                exc_info=True,
            )

    records.sort(key=lambda r: r.period, reverse=True)
    logger.info("fetch_eia_data: retrieved %d EIA record(s)", len(records))
    return records


@with_retry()
def _call_llm_classify(prompt: str) -> str:
    """
    Invoke the LLM and return the raw text response.

    Decorated with @with_retry() so transient network/rate-limit errors are
    retried before propagating to classify_event.

    Args:
        prompt: Formatted classification prompt.

    Returns:
        Raw string content from the LLM response.

    Raises:
        requests.HTTPError / tenacity.RetryError: After all retry attempts.
    """
    llm = LLMWrapper(model_id=_CLASSIFY_MODEL_ID)
    return llm.complete(prompt, temperature=0.0, max_tokens=_CLASSIFY_MAX_TOKENS).content


def classify_event(article: dict[str, object]) -> DetectedEvent | None:
    """
    Classify a raw article dict into a typed, scored DetectedEvent using an LLM.

    Routes through src/core/llm_wrapper.py — never imports the provider SDK directly.
    Returns None if the article is not energy-market-relevant or if the LLM
    response cannot be parsed into a valid DetectedEvent.

    The event_id is derived deterministically from the article URL (SHA-256 prefix)
    so re-classifying the same article is idempotent.

    Args:
        article: Raw article dict with at minimum title and url. Optional keys:
            description, publishedAt (or seendate), source (dict with name key).

    Returns:
        Validated DetectedEvent on success; None if irrelevant or parse failure.
    """
    url = str(article.get("url", ""))
    title = str(article.get("title", ""))
    description = str(article.get("description", title))
    published_at = str(article.get("publishedAt") or article.get("seendate", ""))

    source_raw = article.get("source", {})
    source_name: str = (
        source_raw.get("name", "unknown") if isinstance(source_raw, dict) else str(source_raw)
    )

    event_id = hashlib.sha256(url.encode()).hexdigest()[:16]

    prompt = _CLASSIFY_PROMPT_TEMPLATE.format(
        title=title,
        source=source_name,
        published_at=published_at,
        description=description,
    )

    try:
        raw_content = _call_llm_classify(prompt)
        parsed_dict: object = json.loads(raw_content)
        classified = ClassifyLLMResponse.model_validate(parsed_dict)
    except json.JSONDecodeError:
        logger.warning("classify_event: LLM returned non-JSON for event_id=%s; skipping", event_id)
        return None
    except ValidationError:
        logger.warning(
            "classify_event: LLM response failed schema validation for event_id=%s; skipping",
            event_id,
            exc_info=True,
        )
        return None
    except Exception:
        logger.warning(
            "classify_event: LLM call failed for event_id=%s; skipping",
            event_id,
            exc_info=True,
        )
        return None

    if not classified.is_relevant:
        logger.debug("classify_event: article not relevant, event_id=%s", event_id)
        return None

    # Parse detected_at from article timestamp
    try:
        detected_at = (
            datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if published_at
            else datetime.now(tz=UTC)
        )
    except ValueError:
        detected_at = datetime.now(tz=UTC)

    try:
        event = DetectedEvent(
            event_id=event_id,
            event_type=EventType(classified.event_type),
            description=classified.description,
            source=source_name,
            confidence_score=classified.confidence_score,
            intensity=EventIntensity(classified.intensity),
            detected_at=detected_at,
            affected_instruments=classified.affected_instruments,
            raw_headline=title,
        )
    except (ValidationError, TypeError, ValueError):
        logger.warning(
            "classify_event: DetectedEvent construction failed for event_id=%s; skipping",
            event_id,
            exc_info=True,
        )
        return None

    return event


_MS_PER_SECOND: int = 1000


def run_event_detection() -> list[DetectedEvent]:
    """
    Execute one full event detection cycle.

    Fetches articles from NewsAPI and GDELT, classifies each with the LLM,
    persists detected events and EIA inventory records to PostgreSQL, and
    emits a structured JSON cycle-complete log.

    Each source and DB write runs in an independent try/except — one failure
    never aborts the others. The function never raises.

    Returns:
        List of DetectedEvent objects classified in this cycle. EIA records
        are persisted to eia_inventory and not included in the return value.
    """
    start_time = datetime.now(tz=UTC)
    errors: list[str] = []
    news_articles: list[dict[str, object]] = []
    gdelt_articles: list[dict[str, object]] = []

    # --- Fetch feeds ---
    try:
        news_articles = fetch_news_events()
    except Exception as exc:
        logger.exception("fetch_news_events failed")
        errors.append(f"fetch_news_events: {exc}")

    try:
        gdelt_articles = fetch_gdelt_events()
    except Exception as exc:
        logger.exception("fetch_gdelt_events failed")
        errors.append(f"fetch_gdelt_events: {exc}")

    # --- Classify articles ---
    all_articles = news_articles + gdelt_articles
    events: list[DetectedEvent] = []
    for article in all_articles:
        result = classify_event(article)
        if result is not None:
            events.append(result)

    # --- Persist to PostgreSQL ---
    events_written = 0
    _engine = None
    try:
        _engine = get_engine()
    except Exception as exc:
        logger.exception("run_event_detection: failed to acquire DB engine")
        errors.append(f"get_engine: {exc}")

    if _engine is not None and events:
        try:
            events_written = write_detected_events(events, _engine)
        except Exception as exc:
            logger.exception("write_detected_events failed; events not persisted")
            errors.append(f"write_detected_events: {exc}")

    # --- Fetch and persist EIA inventory ---
    try:
        eia_records = fetch_eia_data()
        if _engine is not None and eia_records:
            try:
                write_eia_records(eia_records, _engine)
            except Exception as exc:
                logger.exception("write_eia_records failed; EIA records not persisted")
                errors.append(f"write_eia_records: {exc}")
    except Exception as exc:
        logger.exception("fetch_eia_data failed")
        errors.append(f"fetch_eia_data: {exc}")

    # --- Structured cycle log ---
    end_time = datetime.now(tz=UTC)
    duration_ms = int((end_time - start_time).total_seconds() * _MS_PER_SECOND)
    logger.info(
        json.dumps(
            {
                "event": "event_detection_cycle_complete",
                "news_articles": len(news_articles),
                "gdelt_articles": len(gdelt_articles),
                "events_classified": len(events),
                "events_written": events_written,
                "error_count": len(errors),
                "errors": errors,
                "duration_ms": duration_ms,
            }
        )
    )

    return events
