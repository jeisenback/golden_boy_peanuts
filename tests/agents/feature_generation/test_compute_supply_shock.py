"""
Unit tests for compute_supply_shock_probability() (issue #106).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.agents.event_detection.models import DetectedEvent, EventIntensity, EventType
from src.agents.feature_generation.feature_generation_agent import (
    compute_supply_shock_probability,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_type: EventType = EventType.SUPPLY_DISRUPTION,
    intensity: EventIntensity = EventIntensity.HIGH,
    confidence_score: float = 1.0,
) -> DetectedEvent:
    return DetectedEvent(
        event_id="test-id",
        event_type=event_type,
        description="test event",
        source="newsapi",
        confidence_score=confidence_score,
        intensity=intensity,
        detected_at=datetime.now(tz=UTC),
    )


# ---------------------------------------------------------------------------
# Empty list
# ---------------------------------------------------------------------------


class TestComputeSupplyShockEmpty:
    def test_empty_list_returns_none(self) -> None:
        assert compute_supply_shock_probability([]) is None


# ---------------------------------------------------------------------------
# Single event
# ---------------------------------------------------------------------------


class TestComputeSupplyShockSingleEvent:
    def test_high_supply_disruption_confidence_1_returns_1(self) -> None:
        # TYPE_WEIGHT[supply_disruption]=1.0, INTENSITY_WEIGHT[high]=1.0, conf=1.0 → 1.0
        event = _make_event(EventType.SUPPLY_DISRUPTION, EventIntensity.HIGH, 1.0)
        result = compute_supply_shock_probability([event])
        assert result == pytest.approx(1.0)

    def test_medium_refinery_outage_confidence_1(self) -> None:
        # TYPE_WEIGHT[refinery_outage]=0.9, INTENSITY_WEIGHT[medium]=0.6, conf=1.0 → 0.54
        event = _make_event(EventType.REFINERY_OUTAGE, EventIntensity.MEDIUM, 1.0)
        result = compute_supply_shock_probability([event])
        assert result == pytest.approx(0.54)

    def test_low_geopolitical_confidence_half(self) -> None:
        # TYPE_WEIGHT[geopolitical]=0.5, INTENSITY_WEIGHT[low]=0.3, conf=0.5 → 0.075
        event = _make_event(EventType.GEOPOLITICAL, EventIntensity.LOW, 0.5)
        result = compute_supply_shock_probability([event])
        assert result == pytest.approx(0.075)

    def test_unknown_type_low_intensity(self) -> None:
        # TYPE_WEIGHT[unknown]=0.1, INTENSITY_WEIGHT[low]=0.3, conf=1.0 → 0.03
        event = _make_event(EventType.UNKNOWN, EventIntensity.LOW, 1.0)
        result = compute_supply_shock_probability([event])
        assert result == pytest.approx(0.03)

    def test_sanctions_high_intensity(self) -> None:
        # TYPE_WEIGHT[sanctions]=0.4, INTENSITY_WEIGHT[high]=1.0, conf=1.0 → 0.4
        event = _make_event(EventType.SANCTIONS, EventIntensity.HIGH, 1.0)
        result = compute_supply_shock_probability([event])
        assert result == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Multiple events
# ---------------------------------------------------------------------------


class TestComputeSupplyShockMultipleEvents:
    def test_multiple_low_events_cumulate(self) -> None:
        # Three low-intensity unknowns: 3 * (0.1 * 0.3 * 1.0) = 0.09
        events = [
            _make_event(EventType.UNKNOWN, EventIntensity.LOW, 1.0),
            _make_event(EventType.UNKNOWN, EventIntensity.LOW, 1.0),
            _make_event(EventType.UNKNOWN, EventIntensity.LOW, 1.0),
        ]
        result = compute_supply_shock_probability(events)
        assert result == pytest.approx(0.09)

    def test_score_capped_at_1(self) -> None:
        # Two max-weight events would sum to 2.0 — must be capped at 1.0
        events = [
            _make_event(EventType.SUPPLY_DISRUPTION, EventIntensity.HIGH, 1.0),
            _make_event(EventType.SUPPLY_DISRUPTION, EventIntensity.HIGH, 1.0),
        ]
        result = compute_supply_shock_probability(events)
        assert result == pytest.approx(1.0)

    def test_mixed_types_sum_correctly(self) -> None:
        # supply_disruption HIGH 1.0 = 1.0*1.0*1.0 = 1.0
        # geopolitical LOW 0.5      = 0.5*0.3*0.5  = 0.075
        # total = 1.075 → capped at 1.0
        events = [
            _make_event(EventType.SUPPLY_DISRUPTION, EventIntensity.HIGH, 1.0),
            _make_event(EventType.GEOPOLITICAL, EventIntensity.LOW, 0.5),
        ]
        result = compute_supply_shock_probability(events)
        assert result == pytest.approx(1.0)

    def test_result_never_exceeds_1(self) -> None:
        events = [_make_event(confidence_score=1.0) for _ in range(10)]
        result = compute_supply_shock_probability(events)
        assert result is not None
        assert result <= 1.0

    def test_result_is_float_not_none_when_events_present(self) -> None:
        event = _make_event()
        result = compute_supply_shock_probability([event])
        assert isinstance(result, float)
