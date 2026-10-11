"""
Pipeline Orchestrator

Wires the four agents into a single end-to-end evaluation cycle:

    Ingestion → Event Detection → Feature Generation → Strategy Evaluation

This module is the entry point for running the full pipeline. Individual
agents can also be called in isolation for testing or partial runs.

Phase 2 data flow:
    1. run_ingestion()           → MarketState
    2. run_event_detection()     → list[DetectedEvent]  (independent of ingestion)
    3. run_alternative_data_ingestion() → AlternativeDataState  (independent of ingestion)
    4. run_feature_generation(market_state, events=events,
                              alternative_data_state=alt_state) → FeatureSet
    5. evaluate_strategies(feature_set) → list[StrategyCandidate]

Event detection failures are non-fatal: the pipeline continues with an empty
events list (degraded mode) so that ingestion and feature generation still
produce actionable candidates. Alternative-data failures are non-fatal in the
same way: the tanker, insider and narrative signals stay None.

ESOD constraints: Python 3.11+, type hints on all public functions,
no langchain.*/langgraph.* imports, DATABASE_URL from environment.
"""

from __future__ import annotations

import logging

from src.agents.alternative_data.alternative_data_agent import run_alternative_data_ingestion
from src.agents.alternative_data.models import AlternativeDataState
from src.agents.event_detection.event_detection_agent import (
    EventDetectionError,
    run_event_detection,
)
from src.agents.event_detection.models import DetectedEvent
from src.agents.feature_generation.feature_generation_agent import run_feature_generation
from src.agents.ingestion.ingestion_agent import run_ingestion
from src.agents.strategy_evaluation.models import StrategyCandidate
from src.agents.strategy_evaluation.strategy_evaluation_agent import evaluate_strategies

logger = logging.getLogger(__name__)


def run_pipeline() -> list[StrategyCandidate]:
    """
    Execute one full pipeline evaluation cycle.

    Call sequence:
        1. run_ingestion()            → MarketState
        2. run_event_detection()      → list[DetectedEvent]
        3. run_alternative_data_ingestion() → AlternativeDataState
        4. run_feature_generation(    → FeatureSet
               market_state,
               events=events,
               alternative_data_state=alt_state,
           )
        5. evaluate_strategies(       → list[StrategyCandidate]
               feature_set
           )

    Degraded Mode:
        Event detection runs independently and may fail (network outage, API rate limits,
        LLM service unavailable, etc.). On failure, the pipeline logs a WARNING and
        continues with events=[], allowing ingestion and feature generation to produce
        candidates based on market signals alone.

        This graceful degradation ensures a partial outage in the event detection layer
        does not suppress the entire pipeline. The returned candidate list is valid but
        may lack event-driven signals.

        Alternative-data ingestion (issue #236) degrades the same way: on failure the
        pipeline logs a WARNING and passes alternative_data_state=None, so the tanker,
        insider and narrative signals are None. run_alternative_data_ingestion() itself
        never raises and reports per-feed failures in alternative_data_errors, which are
        logged here.

    Returns:
        Ranked list of StrategyCandidate objects, sorted by edge_score descending.
        Returns an empty list if no viable candidates are found.
        May return candidates with degraded signal set (no events) on event detection failure.

    Raises:
        RuntimeError: If DATABASE_URL is not set or run_ingestion() fails fatally.

    Note:
        EventDetectionError is intentionally caught and not re-raised. Event detection
        failure is non-fatal: the pipeline continues with events=[] (degraded mode) and
        still returns candidates based on market signals alone.
    """
    logger.info("Pipeline cycle starting")

    market_state = run_ingestion()
    logger.info(
        "Ingestion complete: %d price(s), %d option(s), %d error(s)",
        len(market_state.prices),
        len(market_state.options),
        len(market_state.ingestion_errors),
    )

    events: list[DetectedEvent] = []
    try:
        events = run_event_detection()
    except EventDetectionError as exc:
        logger.warning("Event detection failed (degraded mode); continuing with events=[]: %s", exc)
    logger.info("Event detection complete: %d event(s)", len(events))

    alternative_data_state: AlternativeDataState | None = None
    try:
        alternative_data_state = run_alternative_data_ingestion()
    except Exception as exc:
        logger.warning(
            "Alternative data ingestion failed (degraded mode); continuing without it: %s", exc
        )
    if alternative_data_state is not None:
        logger.info(
            "Alternative data complete: %d insider trade(s), %d narrative signal(s), "
            "%d shipping event(s), %d error(s)",
            len(alternative_data_state.insider_trades),
            len(alternative_data_state.narrative_signals),
            len(alternative_data_state.shipping_events),
            len(alternative_data_state.alternative_data_errors),
        )

    feature_set = run_feature_generation(
        market_state, events=events, alternative_data_state=alternative_data_state
    )
    logger.info(
        "Feature generation complete: %d gap(s), dispersion=%s, %d error(s)",
        len(feature_set.volatility_gaps),
        feature_set.sector_dispersion,
        len(feature_set.feature_errors),
    )

    candidates = evaluate_strategies(feature_set)
    logger.info("Strategy evaluation complete: %d candidate(s)", len(candidates))

    return candidates
