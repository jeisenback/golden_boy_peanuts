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

from src.agents.event_detection.models import (
    ClassifyLLMResponse,
    DetectedEvent,
    EventIntensity,
    EventType,
)
from src.core.llm_wrapper import LLMWrapper
from src.core.retry import with_retry

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT_SECONDS: int = 10

# NewsAPI query for energy market relevance
_NEWSAPI_QUERY: str = "crude oil OR WTI OR Brent OR energy supply OR OPEC"
_NEWSAPI_BASE_URL: str = "https://newsapi.org/v2/everything"
_NEWSAPI_PAGE_SIZE: int = 20

# GDELT Doc API v2 query and parameters
_GDELT_QUERY: str = "crude oil supply disruption OR OPEC OR refinery"
_GDELT_MAX_RECORDS: int = 20
_GDELT_TIMESPAN_MINUTES: int = 1440  # 24 hours

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


def run_event_detection() -> list[DetectedEvent]:
    """
    Execute one full event detection cycle.

    Returns:
        List of DetectedEvent objects detected in this cycle.

    Raises:
        NotImplementedError: Until implemented in issue #105.
    """
    raise NotImplementedError(
        "run_event_detection not yet implemented. "
        "TODO: Orchestrate fetch_news_events, fetch_gdelt_events, classify_event, "
        "write_detected_events. See issue #105."
    )
