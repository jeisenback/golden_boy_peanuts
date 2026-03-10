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

from src.agents.event_detection.event_detection_agent import run_event_detection  # noqa: F401
from src.agents.event_detection.models import DetectedEvent  # noqa: F401
from src.agents.feature_generation.feature_generation_agent import (  # noqa: F401
    run_feature_generation,
)
from src.agents.feature_generation.models import FeatureSet  # noqa: F401
from src.agents.ingestion.ingestion_agent import run_ingestion  # noqa: F401
from src.agents.ingestion.models import MarketState  # noqa: F401
from src.agents.strategy_evaluation.models import StrategyCandidate
from src.agents.strategy_evaluation.strategy_evaluation_agent import (  # noqa: F401
    evaluate_strategies,
)

logger = logging.getLogger(__name__)


def run_pipeline() -> list[StrategyCandidate]:
    """
    Execute one full pipeline evaluation cycle.

    Call sequence:
        1. run_ingestion()            → MarketState
        2. run_event_detection()      → list[DetectedEvent]  (Phase 1: unused)
        3. run_feature_generation(    → FeatureSet
               market_state,
               events=[],             ← Phase 1: hardcoded empty list
           )
        4. evaluate_strategies(       → list[StrategyCandidate]
               feature_set
           )

    Phase 1 note: events from run_event_detection() are not yet passed into
    run_feature_generation(). Replace events=[] with the run_event_detection()
    result when Phase 2 event signals are implemented (see PRD Section 3).

    Returns:
        Ranked list of StrategyCandidate objects, sorted by edge_score descending.
        Returns an empty list if no viable candidates are found.

    Raises:
        RuntimeError: If DATABASE_URL is not set.
        NotImplementedError: Until all four agents are implemented.
    """
    raise NotImplementedError(
        "run_pipeline not yet implemented. "
        "TODO: Call run_ingestion(), run_event_detection(), "
        "run_feature_generation(market_state, events=[]), "
        "evaluate_strategies(feature_set). "
        "Phase 1: pass events=[] to run_feature_generation. "
        "Phase 2: pass run_event_detection() result instead."
    )
