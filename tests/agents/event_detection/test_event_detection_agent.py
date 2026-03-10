"""
Unit tests for the Event Detection Agent.

Coverage goal (expand per GitHub Issue):
  - run_event_detection: returns list of DetectedEvent
  - classify_event: correct EventType and intensity for known headlines
  - fetch_news_events: retry behavior on API failure
"""

import pytest

from src.agents.event_detection.event_detection_agent import run_event_detection
from src.agents.event_detection.models import DetectedEvent


class TestRunEventDetection:
    """Tests for run_event_detection() orchestration function."""

    @pytest.mark.xfail(reason="Not yet implemented", strict=True)
    def test_run_event_detection_returns_list(self) -> None:
        """run_event_detection() must return a list of DetectedEvent instances."""
        result = run_event_detection()
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, DetectedEvent)

    @pytest.mark.xfail(reason="Not yet implemented", strict=True)
    def test_detected_event_confidence_in_range(self) -> None:
        """All DetectedEvent confidence_score values must be in [0.0, 1.0]."""
        result = run_event_detection()
        for event in result:
            assert 0.0 <= event.confidence_score <= 1.0
