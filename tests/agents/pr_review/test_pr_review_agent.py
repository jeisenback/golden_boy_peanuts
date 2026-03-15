"""
Unit tests for the PR Review Agent.

All tests use synthetic PRMetadata — no real GitHub API or LLM calls.
The LLMWrapper is patched to raise NotImplementedError (the pre-implementation
state) so static checks are tested in isolation.

Coverage:
  - Static check: branch name convention
  - Static check: PR targeting main directly
  - Static check: langchain import detection in diff
  - Static check: type-hint heuristic
  - review_pull_request: approved=True when no blockers
  - review_pull_request: approved=False when blockers exist
  - review_pull_request: LLMWrapper NotImplementedError is handled gracefully
  - PRMetadata: Pydantic validation rejects invalid data
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
import pytest

from src.agents.pr_review.models import PRMetadata, ReviewSeverity
from src.agents.pr_review.pr_review_agent import (
    _check_branch_name,
    _check_langchain_imports,
    _check_target_branch,
    _check_type_hints,
    review_pull_request,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TS = datetime.now(tz=UTC)


def _make_metadata(**overrides: object) -> PRMetadata:
    """Return a valid PRMetadata with sensible defaults, overridable per test."""
    defaults: dict[str, object] = {
        "pr_number": 42,
        "title": "feat(ingestion): implement fetch_crude_prices (#8)",
        "body": "Implements WTI and Brent price fetching via Alpha Vantage.",
        "base_branch": "develop",
        "head_branch": "feature/8-fetch-crude-prices",
        "author": "test-author",
        "changed_files": ["src/agents/ingestion/ingestion_agent.py"],
        "diff": "",
        "created_at": _TS,
    }
    defaults.update(overrides)
    return PRMetadata(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _check_branch_name
# ---------------------------------------------------------------------------


class TestCheckBranchName:
    def test_valid_feature_branch_passes(self) -> None:
        meta = _make_metadata(head_branch="feature/8-fetch-crude-prices")
        assert _check_branch_name(meta) == []

    def test_valid_fix_branch_passes(self) -> None:
        meta = _make_metadata(head_branch="fix/12-null-price-guard")
        assert _check_branch_name(meta) == []

    def test_valid_refactor_branch_passes(self) -> None:
        meta = _make_metadata(head_branch="refactor/3-extract-get-engine")
        assert _check_branch_name(meta) == []

    def test_bare_feature_name_fails(self) -> None:
        meta = _make_metadata(head_branch="my-feature")
        findings = _check_branch_name(meta)
        assert len(findings) == 1
        assert findings[0].severity == ReviewSeverity.BLOCKER
        assert findings[0].rule == "git-workflow:branch-name"

    def test_missing_issue_number_fails(self) -> None:
        meta = _make_metadata(head_branch="feature/fetch-crude-prices")
        findings = _check_branch_name(meta)
        assert len(findings) == 1
        assert findings[0].severity == ReviewSeverity.BLOCKER

    def test_uppercase_in_slug_fails(self) -> None:
        meta = _make_metadata(head_branch="feature/8-FetchCrudePrices")
        findings = _check_branch_name(meta)
        assert len(findings) == 1

    def test_claude_branch_prefix_exempt(self) -> None:
        # claude/* branches are system-assigned session branches — exempt from SDLC naming
        meta = _make_metadata(head_branch="claude/create-pr-review-agent-4c3hy")
        findings = _check_branch_name(meta)
        assert len(findings) == 0  # exempted, no blocker

    def test_develop_branch_exempt(self) -> None:
        # develop is the protected integration branch — exempt from feature-branch naming
        meta = _make_metadata(head_branch="develop")
        findings = _check_branch_name(meta)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# _check_target_branch
# ---------------------------------------------------------------------------


class TestCheckTargetBranch:
    def test_targeting_develop_passes(self) -> None:
        meta = _make_metadata(base_branch="develop")
        assert _check_target_branch(meta) == []

    def test_targeting_main_is_blocker(self) -> None:
        meta = _make_metadata(base_branch="main")
        findings = _check_target_branch(meta)
        assert len(findings) == 1
        assert findings[0].severity == ReviewSeverity.BLOCKER
        assert findings[0].rule == "git-workflow:no-direct-to-main"

    def test_develop_to_main_release_exempt(self) -> None:
        # develop → main is the valid release path; not a direct-to-main violation
        meta = _make_metadata(head_branch="develop", base_branch="main")
        findings = _check_target_branch(meta)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# _check_langchain_imports
# ---------------------------------------------------------------------------

_CLEAN_DIFF = """\
diff --git a/src/agents/ingestion/ingestion_agent.py b/src/agents/ingestion/ingestion_agent.py
--- a/src/agents/ingestion/ingestion_agent.py
+++ b/src/agents/ingestion/ingestion_agent.py
@@ -1,3 +1,4 @@
+import logging
 import os
"""

_LANGCHAIN_DIFF = """\
diff --git a/src/agents/ingestion/ingestion_agent.py b/src/agents/ingestion/ingestion_agent.py
--- a/src/agents/ingestion/ingestion_agent.py
+++ b/src/agents/ingestion/ingestion_agent.py
@@ -1,3 +1,4 @@
+from langchain.llms import OpenAI
 import os
"""

_LANGGRAPH_DIFF = """\
diff --git a/src/core/pipeline.py b/src/core/pipeline.py
--- a/src/core/pipeline.py
+++ b/src/core/pipeline.py
@@ -1,2 +1,3 @@
+import langgraph.graph as lg
 import logging
"""


class TestCheckLangchainImports:
    def test_clean_diff_passes(self) -> None:
        meta = _make_metadata(diff=_CLEAN_DIFF)
        assert _check_langchain_imports(meta) == []

    def test_no_diff_passes(self) -> None:
        meta = _make_metadata(diff="")
        assert _check_langchain_imports(meta) == []

    def test_langchain_import_is_blocker(self) -> None:
        meta = _make_metadata(diff=_LANGCHAIN_DIFF)
        findings = _check_langchain_imports(meta)
        assert len(findings) == 1
        assert findings[0].severity == ReviewSeverity.BLOCKER
        assert findings[0].rule == "ESOD:no-langchain"

    def test_langgraph_import_is_blocker(self) -> None:
        meta = _make_metadata(diff=_LANGGRAPH_DIFF)
        findings = _check_langchain_imports(meta)
        assert len(findings) == 1
        assert findings[0].severity == ReviewSeverity.BLOCKER

    def test_removed_langchain_import_ignored(self) -> None:
        # Lines starting with '-' are removals — should not trigger
        diff = _LANGCHAIN_DIFF.replace("+from langchain", "-from langchain")
        meta = _make_metadata(diff=diff)
        assert _check_langchain_imports(meta) == []


# ---------------------------------------------------------------------------
# _check_type_hints
# ---------------------------------------------------------------------------

_TYPED_DIFF = """\
diff --git a/src/agents/ingestion/ingestion_agent.py b/src/agents/ingestion/ingestion_agent.py
--- a/src/agents/ingestion/ingestion_agent.py
+++ b/src/agents/ingestion/ingestion_agent.py
@@ -1,2 +1,4 @@
+def fetch_prices(symbol: str) -> list[float]:
+    return []
"""

_UNTYPED_DIFF = """\
diff --git a/src/agents/ingestion/ingestion_agent.py b/src/agents/ingestion/ingestion_agent.py
--- a/src/agents/ingestion/ingestion_agent.py
+++ b/src/agents/ingestion/ingestion_agent.py
@@ -1,2 +1,4 @@
+def fetch_prices(symbol):
+    return []
"""

_PRIVATE_UNTYPED_DIFF = """\
diff --git a/src/agents/ingestion/ingestion_agent.py b/src/agents/ingestion/ingestion_agent.py
--- a/src/agents/ingestion/ingestion_agent.py
+++ b/src/agents/ingestion/ingestion_agent.py
@@ -1,2 +1,4 @@
+def _private_helper(x):
+    pass
"""


class TestCheckTypeHints:
    def test_typed_public_function_passes(self) -> None:
        meta = _make_metadata(diff=_TYPED_DIFF)
        assert _check_type_hints(meta) == []

    def test_untyped_public_function_is_warning(self) -> None:
        meta = _make_metadata(diff=_UNTYPED_DIFF)
        findings = _check_type_hints(meta)
        assert len(findings) == 1
        assert findings[0].severity == ReviewSeverity.WARNING
        assert findings[0].rule == "ESOD:type-hints"

    def test_untyped_private_function_ignored(self) -> None:
        meta = _make_metadata(diff=_PRIVATE_UNTYPED_DIFF)
        assert _check_type_hints(meta) == []

    def test_no_diff_passes(self) -> None:
        meta = _make_metadata(diff="")
        assert _check_type_hints(meta) == []


# ---------------------------------------------------------------------------
# review_pull_request — integration of all checks
# ---------------------------------------------------------------------------


class TestReviewPullRequest:
    def _patched_review(self, metadata: PRMetadata) -> PRReviewResult:  # type: ignore[name-defined]  # noqa: F821
        """Run review with LLMWrapper patched to raise NotImplementedError."""
        with patch("src.agents.pr_review.pr_review_agent.LLMWrapper") as mock_wrapper_cls:
            mock_instance = MagicMock()
            mock_instance.complete.side_effect = NotImplementedError("not implemented")
            mock_wrapper_cls.return_value = mock_instance
            return review_pull_request(metadata)

    def test_clean_pr_is_approved(self) -> None:
        meta = _make_metadata(diff=_CLEAN_DIFF)
        result = self._patched_review(meta)
        assert result.approved is True
        assert result.blocker_count == 0

    def test_langchain_import_blocks_approval(self) -> None:
        meta = _make_metadata(diff=_LANGCHAIN_DIFF)
        result = self._patched_review(meta)
        assert result.approved is False
        assert result.blocker_count >= 1

    def test_main_target_blocks_approval(self) -> None:
        meta = _make_metadata(base_branch="main")
        result = self._patched_review(meta)
        assert result.approved is False
        assert result.blocker_count >= 1

    def test_bad_branch_name_blocks_approval(self) -> None:
        meta = _make_metadata(head_branch="my-random-branch")
        result = self._patched_review(meta)
        assert result.approved is False
        assert result.blocker_count >= 1

    def test_findings_sorted_blockers_first(self) -> None:
        # Bad branch (blocker) + untyped function (warning) in same PR
        meta = _make_metadata(
            head_branch="my-random-branch",
            diff=_UNTYPED_DIFF,
        )
        result = self._patched_review(meta)
        severities = [f.severity for f in result.findings]
        blocker_indices = [i for i, s in enumerate(severities) if s == ReviewSeverity.BLOCKER]
        warning_indices = [i for i, s in enumerate(severities) if s == ReviewSeverity.WARNING]
        # All blockers must appear before all warnings
        if blocker_indices and warning_indices:
            assert max(blocker_indices) < min(warning_indices)

    def test_llm_not_implemented_does_not_crash(self) -> None:
        """Static checks must still return even if LLM step raises NotImplementedError."""
        meta = _make_metadata(diff=_CLEAN_DIFF)
        result = self._patched_review(meta)
        assert result is not None
        assert isinstance(result.summary, str)

    def test_result_counts_match_findings_list(self) -> None:
        meta = _make_metadata(
            head_branch="my-random-branch",
            diff=_UNTYPED_DIFF,
        )
        result = self._patched_review(meta)

        assert result.blocker_count == sum(
            1 for f in result.findings if f.severity == ReviewSeverity.BLOCKER
        )
        assert result.warning_count == sum(
            1 for f in result.findings if f.severity == ReviewSeverity.WARNING
        )
        assert result.suggestion_count == sum(
            1 for f in result.findings if f.severity == ReviewSeverity.SUGGESTION
        )


# ---------------------------------------------------------------------------
# PRMetadata validation
# ---------------------------------------------------------------------------


class TestPRMetadataValidation:
    def test_valid_metadata_constructs(self) -> None:
        meta = _make_metadata()
        assert meta.pr_number == 42

    def test_pr_number_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            _make_metadata(pr_number=0)

    def test_title_must_not_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            _make_metadata(title="")


# ---------------------------------------------------------------------------
# LLMWrapper dispatch (unit — no real API call)
# ---------------------------------------------------------------------------


class TestLLMWrapperDispatch:
    def test_unsupported_provider_raises_llm_provider_error(self) -> None:
        import os

        from src.core.llm_wrapper import LLMProviderError, LLMWrapper

        original = os.environ.get("LLM_PROVIDER")
        os.environ["LLM_PROVIDER"] = "unsupported_provider"
        try:
            wrapper = LLMWrapper(model_id="some-model")
            with pytest.raises(LLMProviderError):
                wrapper.complete(prompt="test")
        finally:
            if original is None:
                os.environ.pop("LLM_PROVIDER", None)
            else:
                os.environ["LLM_PROVIDER"] = original

    def test_anthropic_provider_calls_http_complete(self) -> None:
        import os

        import src.core._providers.anthropic_http as anthropic_http_mod
        from src.core.llm_wrapper import LLMResponse, LLMWrapper

        os.environ["LLM_PROVIDER"] = "anthropic"
        fake_raw = {
            "content": [{"type": "text", "text": "hello from mock"}],
            "stop_reason": "end_turn",
            "usage": {},
        }
        with patch.object(anthropic_http_mod, "complete", return_value=fake_raw) as mock_complete:
            wrapper = LLMWrapper(model_id="claude-sonnet-4-6")
            response = wrapper.complete(prompt="test prompt")

        mock_complete.assert_called_once()
        assert isinstance(response, LLMResponse)
        assert response.content == "hello from mock"
        assert response.provider == "anthropic"
        assert response.model_id == "claude-sonnet-4-6"
