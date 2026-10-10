"""
Tests for scripts/run_pr_review.py: comment marker, in-place update, fallbacks, and
exit codes (issue #214).
"""

from __future__ import annotations

from datetime import UTC, datetime
import pathlib as _pathlib
import subprocess
import sys as _sys
from unittest.mock import patch

import pytest

from tools.agents.pr_review.models import PRMetadata, PRReviewResult

_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[4]))
from scripts import run_pr_review as runner  # type: ignore[import]

_RUN = "scripts.run_pr_review._run"


def _called_process_error() -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(1, ["gh"])


class TestFormatComment:
    def test_starts_with_hidden_marker(self) -> None:
        body = runner.format_comment("summary", "_No findings._", approved=True)
        assert body.startswith(runner._COMMENT_MARKER)

    def test_clean_status_line(self) -> None:
        body = runner.format_comment("summary", "table", approved=True)
        assert "No blockers — eligible for merge" in body

    def test_blocked_status_line(self) -> None:
        body = runner.format_comment("summary", "table", approved=False)
        assert "Blockers found" in body

    def test_llm_unavailable_is_stated_and_status_does_not_overclaim(self) -> None:
        body = runner.format_comment(
            "summary", "table", approved=True, llm_unavailable_reason="HTTPError (HTTP 400)"
        )
        assert "LLM review unavailable:" in body
        assert "HTTPError (HTTP 400)" in body
        assert "eligible for merge" not in body

    def test_coverage_notes_are_listed(self) -> None:
        body = runner.format_comment(
            "summary", "table", approved=True, coverage_notes=["Excluded: a.csv", "Truncated: b.py"]
        )
        assert "- Excluded: a.csv" in body
        assert "- Truncated: b.py" in body

    def test_body_is_capped_below_github_limit(self) -> None:
        body = runner.format_comment("s", "x" * 100_000, approved=True)
        assert len(body) <= runner._MAX_COMMENT_CHARS


class TestPostComment:
    def test_updates_newest_marked_comment_in_place(self) -> None:
        with patch(_RUN, side_effect=["111\n222\n", ""]) as run:
            runner.post_comment(5, "body")
        patch_call = run.call_args_list[1].args[0]
        assert patch_call[:4] == ["gh", "api", "-X", "PATCH"]
        assert patch_call[4].endswith("/issues/comments/222")
        assert "body=body" in patch_call
        assert all(call.args[0][:3] != ["gh", "pr", "comment"] for call in run.call_args_list)

    def test_creates_new_comment_when_none_exists(self) -> None:
        with patch(_RUN, side_effect=["", ""]) as run:
            runner.post_comment(5, "body")
        assert run.call_args_list[1].args[0][:3] == ["gh", "pr", "comment"]

    def test_falls_back_to_new_comment_when_lookup_fails(self) -> None:
        with patch(_RUN, side_effect=[_called_process_error(), ""]) as run:
            runner.post_comment(5, "body")
        assert run.call_args_list[1].args[0][:3] == ["gh", "pr", "comment"]

    def test_falls_back_to_new_comment_when_edit_is_rejected(self) -> None:
        with patch(_RUN, side_effect=["222", _called_process_error(), ""]) as run:
            runner.post_comment(5, "body")
        assert run.call_args_list[2].args[0][:3] == ["gh", "pr", "comment"]


def _result(static_blockers: int, llm_blockers: int) -> PRReviewResult:
    total = static_blockers + llm_blockers
    return PRReviewResult(
        pr_number=5,
        reviewed_at=datetime(2026, 9, 20, tzinfo=UTC),
        summary="s",
        approved=total == 0,
        blocker_count=total,
        static_blocker_count=static_blockers,
    )


def _metadata() -> PRMetadata:
    return PRMetadata(
        pr_number=5,
        title="t",
        base_branch="develop",
        head_branch="fix/214-x",
        author="a",
        created_at=datetime(2026, 9, 20, tzinfo=UTC),
    )


class TestMainExitCode:
    def _run_main(self, result: PRReviewResult) -> int:
        with (
            patch.object(_sys, "argv", ["run_pr_review.py", "--pr", "5"]),
            patch.object(runner, "fetch_pr_metadata", return_value=_metadata()),
            patch.object(runner, "review_pull_request", return_value=result),
        ):
            return int(runner.main())

    def test_static_blocker_fails_ci(self) -> None:
        assert self._run_main(_result(static_blockers=1, llm_blockers=0)) == 1

    def test_llm_only_blocker_does_not_fail_ci(self) -> None:
        assert self._run_main(_result(static_blockers=0, llm_blockers=2)) == 0

    def test_clean_review_passes(self) -> None:
        assert self._run_main(_result(static_blockers=0, llm_blockers=0)) == 0

    def test_metadata_fetch_failure_fails_ci(self) -> None:
        with (
            patch.object(_sys, "argv", ["run_pr_review.py", "--pr", "5"]),
            patch.object(runner, "fetch_pr_metadata", side_effect=RuntimeError("gh down")),
        ):
            assert runner.main() == 1


@pytest.mark.parametrize("pr_number", [1, 999])
def test_lookup_targets_the_issue_comments_endpoint(pr_number: int) -> None:
    with patch(_RUN, return_value="") as run:
        assert runner._find_existing_comment_id(pr_number) is None
    endpoint = run.call_args.args[0][2]
    assert endpoint == f"repos/{{owner}}/{{repo}}/issues/{pr_number}/comments"
