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

import logging
import os

from tenacity import retry, stop_after_attempt, wait_exponential

from src.agents.event_detection.models import DetectedEvent

logger = logging.getLogger(__name__)


@retry(
    stop=stop_after_attempt(int(os.environ.get("TENACITY_MAX_RETRIES", "5"))),
    wait=wait_exponential(
        multiplier=int(os.environ.get("TENACITY_WAIT_MULTIPLIER", "1")),
        max=int(os.environ.get("TENACITY_WAIT_MAX", "60")),
    ),
    reraise=True,
)
def fetch_news_events() -> list[DetectedEvent]:
    """
    Fetch and parse energy-relevant events from NewsAPI.

    Returns:
        Validated DetectedEvent objects.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "fetch_news_events not yet implemented. "
        "TODO: Query NewsAPI for energy keywords. "
        "Parse and validate each result into DetectedEvent. "
        "See .env.example for NEWSAPI_KEY."
    )


def classify_event(headline: str, source: str) -> DetectedEvent:
    """
    Classify a raw headline into a typed, scored DetectedEvent.

    Phase 1 uses keyword-based heuristic scoring.
    ML-based classification is deferred to a future phase (ESOD Section 8).

    Args:
        headline: Raw headline text from the news feed.
        source: Source identifier (e.g., 'newsapi', 'gdelt').

    Returns:
        DetectedEvent with type, confidence_score, and intensity assigned.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "classify_event not yet implemented. "
        "TODO: Apply keyword-based heuristics for Phase 1. "
        "Example: 'Strait of Hormuz' -> EventType.TANKER_CHOKEPOINT, HIGH."
    )


def run_event_detection() -> list[DetectedEvent]:
    """
    Execute one full event detection cycle.

    Returns:
        List of DetectedEvent objects detected in this cycle.

    Raises:
        NotImplementedError: Until implemented.
    """
    raise NotImplementedError(
        "run_event_detection not yet implemented. "
        "TODO: Orchestrate fetch_news_events, classify_event, write_detected_events."
    )
