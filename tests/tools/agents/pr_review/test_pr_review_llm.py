"""
Tests for structured LLM findings, diff chunking, and LLM-failure tolerance in the
PR Review Agent (issue #214).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

from tools.agents.pr_review.models import PRMetadata, ReviewSeverity
from tools.agents.pr_review.pr_review_agent import (
    _parse_llm_findings,
    _plan_review_chunks,
    _split_diff_by_file,
    review_pull_request,
)

_LLM = "tools.agents.pr_review.pr_review_agent.LLMWrapper"


def _file_diff(path: str, lines: int = 3) -> str:
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1 @@\n"
        + "+x = 1\n" * lines
    )


def _meta(diff: str, head_branch: str = "fix/214-review-agent") -> PRMetadata:
    return PRMetadata(
        pr_number=7,
        title="fix(ci): test",
        base_branch="develop",
        head_branch=head_branch,
        author="tester",
        diff=diff,
        created_at=datetime(2026, 9, 20, tzinfo=UTC),
    )


def _wrapper_returning(*contents: str) -> MagicMock:
    wrapper = MagicMock()
    wrapper.complete.side_effect = [MagicMock(content=c) for c in contents]
    return wrapper


_BLOCKER_JSON = (
    '[{"file_path": "src/a.py", "line_number": 4, "severity": "blocker", '
    '"rule": "ESOD-4", "message": "swallowed exception", "suggestion": "re-raise"}]'
)


class TestParseLlmFindings:
    def test_structured_json_keeps_severity_location_and_prefixes_rule(self) -> None:
        findings = _parse_llm_findings(_BLOCKER_JSON, pr_number=7)
        assert len(findings) == 1
        f = findings[0]
        assert f.severity == ReviewSeverity.BLOCKER
        assert f.location == "src/a.py"
        assert f.line_number == 4
        assert f.rule == "llm:ESOD-4"
        assert f.suggestion == "re-raise"

    def test_code_fence_and_uppercase_severity_are_tolerated(self) -> None:
        item = '{"file_path": "a.py", "severity": "WARNING", "rule": "r", "message": "m"}'
        text = f"```json\n[{item}]\n```"
        findings = _parse_llm_findings(text, pr_number=7)
        assert [f.severity for f in findings] == [ReviewSeverity.WARNING]

    @pytest.mark.parametrize("text", ["[]", "No findings.", "  no findings"])
    def test_clean_output_yields_no_findings(self, text: str) -> None:
        assert _parse_llm_findings(text, pr_number=7) == []

    def test_non_json_output_is_surfaced_not_downgraded_silently(self) -> None:
        findings = _parse_llm_findings("Finding 1: something is wrong", pr_number=7)
        assert len(findings) == 1
        assert findings[0].rule == "llm:unparsed"
        assert findings[0].severity == ReviewSeverity.SUGGESTION
        assert "Finding 1" in findings[0].message

    def test_malformed_elements_are_reported_alongside_valid_ones(self) -> None:
        text = (
            '[{"file_path": "a.py", "severity": "blocker", "rule": "r", "message": "m"},'
            ' {"severity": "catastrophic", "rule": "r", "message": "m"}]'
        )
        findings = _parse_llm_findings(text, pr_number=7)
        assert [f.rule for f in findings] == ["llm:r", "llm:unparsed"]
        assert "1 LLM finding" in findings[1].message


class TestSplitAndPlanChunks:
    def test_split_returns_one_section_per_file(self) -> None:
        diff = _file_diff("src/a.py") + _file_diff("tests/test_a.py")
        assert [p for p, _ in _split_diff_by_file(diff)] == ["src/a.py", "tests/test_a.py"]

    def test_data_files_and_heartbeat_are_excluded_and_reported(self) -> None:
        diff = (
            _file_diff("backtests/fixtures/big.csv")
            + _file_diff("HEARTBEAT.md")
            + _file_diff("src/a.py")
        )
        chunks, notes = _plan_review_chunks(diff)
        assert [paths for paths, _ in chunks] == [["src/a.py"]]
        assert "backtests/fixtures/big.csv" in notes[0]
        assert "HEARTBEAT.md" in notes[0]

    def test_code_is_prioritised_over_tests_and_data(self) -> None:
        diff = _file_diff("tests/test_a.py") + _file_diff("docs/x.md") + _file_diff("src/a.py")
        chunks, _ = _plan_review_chunks(diff)
        assert chunks[0][0] == ["src/a.py", "tests/test_a.py", "docs/x.md"]

    def test_files_are_packed_whole_into_budgeted_chunks(self) -> None:
        one = _file_diff("src/a.py", lines=5)
        diff = one + _file_diff("src/b.py", lines=5) + _file_diff("src/c.py", lines=5)
        chunks, notes = _plan_review_chunks(diff, max_chars=len(one) * 2 + 1)
        assert [paths for paths, _ in chunks] == [["src/a.py", "src/b.py"], ["src/c.py"]]
        assert notes == []

    def test_oversized_file_is_truncated_with_a_note(self) -> None:
        chunks, notes = _plan_review_chunks(_file_diff("src/big.py", lines=500), max_chars=200)
        assert len(chunks[0][1]) == 200
        assert any("Truncated" in n and "src/big.py" in n for n in notes)

    def test_chunks_beyond_the_cap_are_dropped_and_named(self) -> None:
        one = _file_diff("src/a.py", lines=5)
        diff = one + _file_diff("src/b.py", lines=5) + _file_diff("src/c.py", lines=5)
        chunks, notes = _plan_review_chunks(diff, max_chars=len(one) + 1, max_chunks=2)
        assert len(chunks) == 2
        assert any("src/c.py" in n and "chunk limit" in n for n in notes)


class TestReviewPullRequestLlm:
    def test_llm_blocker_reaches_status_but_is_not_a_static_blocker(self) -> None:
        with patch(_LLM, return_value=_wrapper_returning(_BLOCKER_JSON)):
            result = review_pull_request(_meta(_file_diff("src/a.py")))
        assert result.blocker_count == 1
        assert result.static_blocker_count == 0
        assert result.approved is False
        assert "1 blocker(s) must be resolved" in result.summary

    def test_one_llm_call_per_chunk(self) -> None:
        wrapper = _wrapper_returning("[]", "[]")
        big = _file_diff("src/a.py", lines=1200) + _file_diff("src/b.py", lines=1200)
        with patch(_LLM, return_value=wrapper):
            review_pull_request(_meta(big))
        assert wrapper.complete.call_count == 2

    def test_only_excluded_files_means_no_llm_call(self) -> None:
        with patch(_LLM) as wrapper_cls:
            result = review_pull_request(_meta(_file_diff("HEARTBEAT.md")))
        wrapper_cls.return_value.complete.assert_not_called()
        assert result.llm_unavailable_reason is None
        assert any("HEARTBEAT.md" in n for n in result.coverage_notes)

    def test_llm_http_error_keeps_static_checks_and_records_reason(self) -> None:
        error = requests.HTTPError("400 Client Error")
        error.response = MagicMock(status_code=400)
        wrapper = MagicMock()
        wrapper.complete.side_effect = error
        with patch(_LLM, return_value=wrapper):
            result = review_pull_request(_meta(_file_diff("src/a.py"), head_branch="bad-branch"))
        assert result.llm_unavailable_reason == "HTTPError (HTTP 400)"
        assert result.static_blocker_count >= 1
        assert any("src/a.py" in n and "provider failure" in n for n in result.coverage_notes)

    def test_llm_failure_alone_does_not_block_approval(self) -> None:
        wrapper = MagicMock()
        wrapper.complete.side_effect = RuntimeError("boom")
        with patch(_LLM, return_value=wrapper):
            result = review_pull_request(_meta(_file_diff("src/a.py")))
        assert result.approved is True
        assert result.llm_unavailable_reason == "RuntimeError"
        assert "incomplete" in result.summary

    def test_failure_on_second_chunk_keeps_first_chunk_findings(self) -> None:
        wrapper = MagicMock()
        wrapper.complete.side_effect = [MagicMock(content=_BLOCKER_JSON), RuntimeError("late")]
        big = _file_diff("src/a.py", lines=1200) + _file_diff("src/b.py", lines=1200)
        with patch(_LLM, return_value=wrapper):
            result = review_pull_request(_meta(big))
        assert result.blocker_count == 1
        assert result.llm_unavailable_reason == "RuntimeError"
        assert any("src/b.py" in n for n in result.coverage_notes)
        assert not any("src/a.py" in n and "provider failure" in n for n in result.coverage_notes)
