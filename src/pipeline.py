"""
Pipeline Orchestrator

Wires the four agents into a single end-to-end evaluation cycle:

    Ingestion → Event Detection → Feature Generation → Strategy Evaluation

This module is the entry point for running the full pipeline. Individual
agents can also be called in isolation for testing or partial runs.

Phase 2 data flow:
    1. run_ingestion()           → MarketState
    2. run_event_detection()     → list[DetectedEvent]  (independent of ingestion)
    3. run_feature_generation(market_state, events=events) → FeatureSet
    4. evaluate_strategies(feature_set) → list[StrategyCandidate]

Event detection failures are non-fatal: the pipeline continues with an empty
events list (degraded mode) so that ingestion and feature generation still
produce actionable candidates.

ESOD constraints: Python 3.11+, type hints on all public functions,
no langchain.*/langgraph.* imports, DATABASE_URL from environment.
"""

from __future__ import annotations

import logging

import requests

from src.agents.event_detection.event_detection_agent import run_event_detection
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
        3. run_feature_generation(    → FeatureSet
               market_state,
               events=events,
           )
        4. evaluate_strategies(       → list[StrategyCandidate]
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

    Returns:
        Ranked list of StrategyCandidate objects, sorted by edge_score descending.
        Returns an empty list if no viable candidates are found.
        May return candidates with degraded signal set (no events) on event detection failure.

    Raises:
        RuntimeError: If DATABASE_URL is not set or run_ingestion() fails fatally.
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
    except (requests.RequestException, RuntimeError) as exc:
        logger.warning("Event detection failed (degraded mode); continuing with events=[]: %s", exc)
    logger.info("Event detection complete: %d event(s)", len(events))

    feature_set = run_feature_generation(market_state, events=events)
    logger.info(
        "Feature generation complete: %d gap(s), dispersion=%s, %d error(s)",
        len(feature_set.volatility_gaps),
        feature_set.sector_dispersion,
        len(feature_set.feature_errors),
    )

    candidates = evaluate_strategies(feature_set)
    logger.info("Strategy evaluation complete: %d candidate(s)", len(candidates))

    return candidates
