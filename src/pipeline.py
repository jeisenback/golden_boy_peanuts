"""
Pipeline Orchestrator

Wires the four agents into a single end-to-end evaluation cycle:

    Ingestion → Event Detection → Feature Generation → Strategy Evaluation

This module is the entry point for running the full pipeline. Individual
agents can also be called in isolation for testing or partial runs.

Phase notes (from PRD Section 3):

  Phase 1 (current): Event Detection runs in parallel with Ingestion but
    its results are NOT yet fed into Feature Generation. The call:

        run_feature_generation(market_state, events=[])

    The empty events list is intentional. When Phase 2 is implemented,
    replace the hardcoded [] with the return value of run_event_detection().

  Phase 2+: run_event_detection() results flow into run_feature_generation().

ESOD constraints: Python 3.11+, type hints on all public functions,
no langchain.*/langgraph.* imports, DATABASE_URL from environment.
"""

from __future__ import annotations

import logging

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
        2. run_feature_generation(    → FeatureSet
               market_state,
               events=[],             ← Phase 1: Event Detection not yet implemented
           )
        3. evaluate_strategies(       → list[StrategyCandidate]
               feature_set
           )

    Phase 1 note: Event Detection (run_event_detection) raises NotImplementedError
    and is skipped. Replace events=[] with run_event_detection() results in Phase 2.

    Returns:
        Ranked list of StrategyCandidate objects, sorted by edge_score descending.
        Returns an empty list if no viable candidates are found.

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

    # Phase 1: Event Detection not yet implemented — pass empty events list.
    # Phase 2: replace [] with run_event_detection() result.
    feature_set = run_feature_generation(market_state, events=[])
    logger.info(
        "Feature generation complete: %d gap(s), dispersion=%s, %d error(s)",
        len(feature_set.volatility_gaps),
        feature_set.sector_dispersion,
        len(feature_set.feature_errors),
    )

    candidates = evaluate_strategies(feature_set)
    logger.info("Strategy evaluation complete: %d candidate(s)", len(candidates))

    return candidates
