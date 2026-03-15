"""
Unit tests for classify_event().

All LLM calls are mocked via unittest.mock.patch so no API key or
network connectivity is required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agents.event_detection.event_detection_agent import classify_event
from src.agents.event_detection.models import DetectedEvent, EventIntensity, EventType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SUPPLY_ARTICLE: dict[str, object] = {
    "title": "OPEC cuts output by 1 million barrels per day",
    "description": "OPEC+ agreed to reduce production to support prices.",
    "url": "https://reuters.com/opec-cut-2026",
    "publishedAt": "2026-03-15T18:00:00Z",
    "source": {"name": "Reuters"},
}

_IRRELEVANT_ARTICLE: dict[str, object] = {
    "title": "Local bakery wins award for best croissant",
    "description": "A bakery in Paris won a national pastry award.",
    "url": "https://example.com/bakery-award",
    "publishedAt": "2026-03-15T10:00:00Z",
    "source": {"name": "FoodNews"},
}

_RELEVANT_LLM_RESPONSE = json.dumps(
    {
        "is_relevant": True,
        "event_type": "supply_disruption",
        "confidence_score": 0.9,
        "intensity": "high",
        "description": "OPEC+ cuts output by 1 mb/d to support crude prices.",
        "affected_instruments": ["USO", "XLE", "CL=F"],
    }
)

_IRRELEVANT_LLM_RESPONSE = json.dumps(
    {
        "is_relevant": False,
        "event_type": "unknown",
        "confidence_score": 0.0,
        "intensity": "low",
        "description": "",
        "affected_instruments": [],
    }
)


def _mock_llm(content: str) -> MagicMock:
    llm_response = MagicMock()
    llm_response.content = content
    wrapper = MagicMock()
    wrapper.complete.return_value = llm_response
    return wrapper


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClassifyEvent:
    def test_relevant_article_returns_detected_event(self) -> None:
        """A supply disruption article produces a valid DetectedEvent."""
        with patch(
            "src.agents.event_detection.event_detection_agent.LLMWrapper",
            return_value=_mock_llm(_RELEVANT_LLM_RESPONSE),
        ):
            result = classify_event(_SUPPLY_ARTICLE)

        assert isinstance(result, DetectedEvent)
        assert result.event_type == EventType.SUPPLY_DISRUPTION
        assert result.intensity == EventIntensity.HIGH
        assert result.confidence_score == pytest.approx(0.9)
        assert "USO" in result.affected_instruments

    def test_irrelevant_article_returns_none(self) -> None:
        """Articles flagged as not relevant by the LLM return None."""
        with patch(
            "src.agents.event_detection.event_detection_agent.LLMWrapper",
            return_value=_mock_llm(_IRRELEVANT_LLM_RESPONSE),
        ):
            result = classify_event(_IRRELEVANT_ARTICLE)

        assert result is None

    def test_event_id_is_deterministic_sha256_prefix(self) -> None:
        """event_id is the first 16 hex chars of SHA-256(url)."""
        import hashlib

        expected_id = hashlib.sha256(str(_SUPPLY_ARTICLE["url"]).encode()).hexdigest()[:16]
        with patch(
            "src.agents.event_detection.event_detection_agent.LLMWrapper",
            return_value=_mock_llm(_RELEVANT_LLM_RESPONSE),
        ):
            result = classify_event(_SUPPLY_ARTICLE)

        assert result is not None
        assert result.event_id == expected_id

    def test_malformed_llm_json_returns_none(self) -> None:
        """Non-JSON LLM response logs a warning and returns None."""
        with patch(
            "src.agents.event_detection.event_detection_agent.LLMWrapper",
            return_value=_mock_llm("this is not json at all"),
        ):
            result = classify_event(_SUPPLY_ARTICLE)

        assert result is None

    def test_llm_exception_returns_none(self) -> None:
        """LLM call failure logs a warning and returns None."""
        wrapper = MagicMock()
        wrapper.complete.side_effect = RuntimeError("LLM unavailable")
        with patch(
            "src.agents.event_detection.event_detection_agent.LLMWrapper",
            return_value=wrapper,
        ):
            result = classify_event(_SUPPLY_ARTICLE)

        assert result is None

    def test_invalid_event_type_from_llm_returns_none(self) -> None:
        """LLM returning an invalid EventType value causes Pydantic error → None."""
        bad_response = json.dumps(
            {
                "is_relevant": True,
                "event_type": "not_a_valid_type",
                "confidence_score": 0.8,
                "intensity": "high",
                "description": "Some event.",
                "affected_instruments": [],
            }
        )
        with patch(
            "src.agents.event_detection.event_detection_agent.LLMWrapper",
            return_value=_mock_llm(bad_response),
        ):
            result = classify_event(_SUPPLY_ARTICLE)

        assert result is None

    def test_raw_headline_set_to_article_title(self) -> None:
        """raw_headline on the DetectedEvent matches the article title."""
        with patch(
            "src.agents.event_detection.event_detection_agent.LLMWrapper",
            return_value=_mock_llm(_RELEVANT_LLM_RESPONSE),
        ):
            result = classify_event(_SUPPLY_ARTICLE)

        assert result is not None
        assert result.raw_headline == _SUPPLY_ARTICLE["title"]

    def test_source_name_extracted_from_source_dict(self) -> None:
        """source field on DetectedEvent uses source.name from article dict."""
        with patch(
            "src.agents.event_detection.event_detection_agent.LLMWrapper",
            return_value=_mock_llm(_RELEVANT_LLM_RESPONSE),
        ):
            result = classify_event(_SUPPLY_ARTICLE)

        assert result is not None
        assert result.source == "Reuters"
