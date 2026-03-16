"""
Unit tests for run_event_detection() orchestration.

All external calls (fetch_*, classify_event, get_engine, write_*) are mocked.
No real API keys, network, or database required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from src.agents.event_detection.event_detection_agent import run_event_detection
from src.agents.event_detection.models import (
    DetectedEvent,
    EventIntensity,
    EventType,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_MODULE = "src.agents.event_detection.event_detection_agent"


def _make_event(event_id: str = "abc123") -> DetectedEvent:
    return DetectedEvent(
        event_id=event_id,
        event_type=EventType.SUPPLY_DISRUPTION,
        description="Test event",
        source="newsapi",
        confidence_score=0.9,
        intensity=EventIntensity.HIGH,
        detected_at=datetime.now(tz=UTC),
        affected_instruments=["CL=F"],
    )


def _patch_all(
    news_return=None,
    gdelt_return=None,
    classify_return=None,
    eia_return=None,
    engine_return=None,
    write_events_return=1,
    news_raises=None,
    gdelt_raises=None,
    eia_raises=None,
    engine_raises=None,
    write_events_raises=None,
):
    """Return a context manager stack patching all external dependencies."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        news_mock = MagicMock(
            return_value=news_return or [],
            side_effect=news_raises,
        )
        gdelt_mock = MagicMock(
            return_value=gdelt_return or [],
            side_effect=gdelt_raises,
        )
        classify_mock = MagicMock(return_value=classify_return)
        eia_mock = MagicMock(
            return_value=eia_return or [],
            side_effect=eia_raises,
        )
        engine_mock = MagicMock() if engine_return is None else engine_return
        if engine_raises:
            engine_mock_fn = MagicMock(side_effect=engine_raises)
        else:
            engine_mock_fn = MagicMock(return_value=engine_mock)

        write_events_mock = MagicMock(
            return_value=write_events_return,
            side_effect=write_events_raises,
        )
        write_eia_mock = MagicMock()

        with (
            patch(f"{_MODULE}.fetch_news_events", news_mock),
            patch(f"{_MODULE}.fetch_gdelt_events", gdelt_mock),
            patch(f"{_MODULE}.classify_event", classify_mock),
            patch(f"{_MODULE}.fetch_eia_data", eia_mock),
            patch(f"{_MODULE}.get_engine", engine_mock_fn),
            patch(f"{_MODULE}.write_detected_events", write_events_mock),
            patch(f"{_MODULE}.write_eia_records", write_eia_mock),
        ):
            yield {
                "news": news_mock,
                "gdelt": gdelt_mock,
                "classify": classify_mock,
                "eia": eia_mock,
                "engine": engine_mock_fn,
                "write_events": write_events_mock,
                "write_eia": write_eia_mock,
            }

    return _ctx()


# ---------------------------------------------------------------------------
# All-sources-success
# ---------------------------------------------------------------------------


class TestRunEventDetectionSuccess:
    def test_returns_classified_events(self) -> None:
        event = _make_event()
        article = {"title": "t", "url": "http://example.com"}
        with _patch_all(
            news_return=[article],
            gdelt_return=[article],
            classify_return=event,
        ):
            result = run_event_detection()

        assert len(result) == 2
        assert all(isinstance(e, DetectedEvent) for e in result)

    def test_none_from_classify_skipped(self) -> None:
        article = {"title": "t", "url": "http://example.com"}
        with _patch_all(
            news_return=[article, article],
            classify_return=None,
        ):
            result = run_event_detection()

        assert result == []

    def test_write_detected_events_called_with_events(self) -> None:
        event = _make_event()
        article = {"title": "t", "url": "http://example.com"}
        with _patch_all(
            news_return=[article],
            classify_return=event,
        ) as mocks:
            run_event_detection()

        mocks["write_events"].assert_called_once()
        written_events = mocks["write_events"].call_args.args[0]
        assert written_events == [event]

    def test_eia_fetched_and_written(self) -> None:
        from src.agents.event_detection.models import EIAInventoryRecord

        eia_rec = EIAInventoryRecord(
            period="2024-10",
            crude_stocks_mb=420.0,
            fetched_at=datetime.now(tz=UTC),
        )
        with _patch_all(eia_return=[eia_rec]) as mocks:
            run_event_detection()

        mocks["write_eia"].assert_called_once()

    def test_returns_list_not_raises(self) -> None:
        with _patch_all():
            result = run_event_detection()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Partial source failure
# ---------------------------------------------------------------------------


class TestRunEventDetectionPartialFailure:
    def test_news_failure_does_not_abort_gdelt(self) -> None:
        event = _make_event()
        article = {"title": "t", "url": "http://example.com"}
        with _patch_all(
            news_raises=RuntimeError("news down"),
            gdelt_return=[article],
            classify_return=event,
        ):
            result = run_event_detection()

        assert len(result) == 1

    def test_gdelt_failure_does_not_abort_news(self) -> None:
        event = _make_event()
        article = {"title": "t", "url": "http://example.com"}
        with _patch_all(
            news_return=[article],
            gdelt_raises=RuntimeError("gdelt down"),
            classify_return=event,
        ):
            result = run_event_detection()

        assert len(result) == 1

    def test_eia_failure_cycle_continues(self) -> None:
        event = _make_event()
        article = {"title": "t", "url": "http://example.com"}
        with _patch_all(
            news_return=[article],
            classify_return=event,
            eia_raises=RuntimeError("eia down"),
        ):
            result = run_event_detection()

        assert len(result) == 1


# ---------------------------------------------------------------------------
# DB failure
# ---------------------------------------------------------------------------


class TestRunEventDetectionDBFailure:
    def test_db_engine_failure_events_still_returned(self) -> None:
        event = _make_event()
        article = {"title": "t", "url": "http://example.com"}
        with _patch_all(
            news_return=[article],
            classify_return=event,
            engine_raises=RuntimeError("db down"),
        ):
            result = run_event_detection()

        assert result == [event]

    def test_write_failure_events_still_returned(self) -> None:
        event = _make_event()
        article = {"title": "t", "url": "http://example.com"}
        with _patch_all(
            news_return=[article],
            classify_return=event,
            write_events_raises=RuntimeError("write failed"),
        ):
            result = run_event_detection()

        assert result == [event]

    def test_no_write_called_when_no_events(self) -> None:
        with _patch_all(classify_return=None) as mocks:
            run_event_detection()

        mocks["write_events"].assert_not_called()

    def test_structured_log_emitted(self, caplog: pytest.LogCaptureFixture) -> None:
        import json
        import logging

        with caplog.at_level(logging.INFO):
            with _patch_all():
                run_event_detection()

        log_line = next(
            (m for m in caplog.messages if "event_detection_cycle_complete" in m),
            None,
        )
        assert log_line is not None
        payload = json.loads(log_line)
        assert "duration_ms" in payload
        assert "events_classified" in payload
        assert "error_count" in payload
        assert "errors" in payload
