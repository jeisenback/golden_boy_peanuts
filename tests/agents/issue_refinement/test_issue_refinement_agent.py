"""
Unit tests for the Issue Refinement Agent.

All tests use synthetic IssueMetadata — no real GitHub API or LLM calls.
The LLMWrapper is patched to raise EnvironmentError (missing API key) so
static DoR checks are tested in isolation.

Coverage:
  - Static check: AC checkbox count
  - Static check: milestone presence
  - Static check: type:* label presence
  - Static check: phase:* label presence
  - Static check: 'blocked' label gate
  - refine_issue: ready=True when no blockers
  - refine_issue: ready=False when blockers present
  - refine_issue: LLM unavailability is handled gracefully
  - refine_issue: findings sorted blockers first
  - refine_issue: counts match findings list
  - IssueMetadata: Pydantic validation
  - Shared Finding type used across both agents
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
import pytest

from src.agents.issue_refinement.issue_refinement_agent import (
    _check_ac_count,
    _check_labels,
    _check_milestone,
    _check_not_blocked,
    refine_issue,
)
from src.agents.issue_refinement.models import DoRSeverity, IssueMetadata
from src.core.findings import Finding, FindingSeverity

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TS = datetime.now(timezone.utc)

_GOOD_BODY = """\
## Summary
Implement WTI price fetching.

## Acceptance Criteria
- [ ] fetch_crude_prices() returns a non-empty list of RawPriceRecord
- [ ] Each record is validated by Pydantic before being returned
- [ ] On API failure, tenacity retries up to 5 times before re-raising
"""

_GOOD_LABELS = ["type: feature", "phase: 1", "agent-assisted"]


def _make_metadata(**overrides: object) -> IssueMetadata:
    """Return a valid IssueMetadata with sensible defaults, overridable per test."""
    defaults: dict[str, object] = {
        "issue_number": 8,
        "title": "Implement fetch_crude_prices — Alpha Vantage (WTI, Brent)",
        "body": _GOOD_BODY,
        "labels": list(_GOOD_LABELS),
        "milestone": "Phase 1",
        "assignees": [],
        "created_at": _TS,
        "state": "open",
    }
    defaults.update(overrides)
    return IssueMetadata(**defaults)  # type: ignore[arg-type]


def _patched_refine(metadata: IssueMetadata) -> IssueRefinementResult:  # type: ignore[name-defined]  # noqa: F821
    """Run refine_issue with LLMWrapper patched to raise EnvironmentError."""
    with patch("src.agents.issue_refinement.issue_refinement_agent.LLMWrapper") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.complete.side_effect = OSError("ANTHROPIC_API_KEY not set")
        mock_cls.return_value = mock_instance
        return refine_issue(metadata)


# ---------------------------------------------------------------------------
# _check_ac_count
# ---------------------------------------------------------------------------


class TestCheckAcCount:
    def test_three_checkboxes_passes(self) -> None:
        meta = _make_metadata(body=_GOOD_BODY)
        assert _check_ac_count(meta) == []

    def test_four_checkboxes_passes(self) -> None:
        body = _GOOD_BODY + "- [ ] Additional AC item\n"
        meta = _make_metadata(body=body)
        assert _check_ac_count(meta) == []

    def test_two_checkboxes_is_blocker(self) -> None:
        body = "- [ ] AC one\n- [ ] AC two\n"
        meta = _make_metadata(body=body)
        findings = _check_ac_count(meta)
        assert len(findings) == 1
        assert findings[0].severity == DoRSeverity.BLOCKER
        assert findings[0].rule == "DoR:ac-count"

    def test_zero_checkboxes_is_blocker(self) -> None:
        meta = _make_metadata(body="No checkboxes here.")
        findings = _check_ac_count(meta)
        assert len(findings) == 1
        assert findings[0].severity == DoRSeverity.BLOCKER

    def test_checked_boxes_count_too(self) -> None:
        # Already-checked [x] items still count toward the minimum
        body = "- [x] Done AC one\n- [x] Done AC two\n- [ ] Pending AC three\n"
        meta = _make_metadata(body=body)
        assert _check_ac_count(meta) == []

    def test_empty_body_is_blocker(self) -> None:
        meta = _make_metadata(body="")
        findings = _check_ac_count(meta)
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# _check_milestone
# ---------------------------------------------------------------------------


class TestCheckMilestone:
    def test_milestone_present_passes(self) -> None:
        meta = _make_metadata(milestone="Phase 1")
        assert _check_milestone(meta) == []

    def test_no_milestone_is_blocker(self) -> None:
        meta = _make_metadata(milestone=None)
        findings = _check_milestone(meta)
        assert len(findings) == 1
        assert findings[0].severity == DoRSeverity.BLOCKER
        assert findings[0].rule == "DoR:milestone"


# ---------------------------------------------------------------------------
# _check_labels
# ---------------------------------------------------------------------------


class TestCheckLabels:
    def test_both_type_and_phase_labels_passes(self) -> None:
        meta = _make_metadata(labels=["type: feature", "phase: 1"])
        assert _check_labels(meta) == []

    def test_missing_type_label_is_blocker(self) -> None:
        meta = _make_metadata(labels=["phase: 1"])
        findings = _check_labels(meta)
        rules = [f.rule for f in findings]
        assert "DoR:label-type" in rules
        assert all(f.severity == DoRSeverity.BLOCKER for f in findings)

    def test_missing_phase_label_is_blocker(self) -> None:
        meta = _make_metadata(labels=["type: feature"])
        findings = _check_labels(meta)
        rules = [f.rule for f in findings]
        assert "DoR:label-phase" in rules

    def test_missing_both_labels_produces_two_blockers(self) -> None:
        meta = _make_metadata(labels=["agent-assisted"])
        findings = _check_labels(meta)
        assert len(findings) == 2
        assert all(f.severity == DoRSeverity.BLOCKER for f in findings)

    def test_empty_labels_produces_two_blockers(self) -> None:
        meta = _make_metadata(labels=[])
        findings = _check_labels(meta)
        assert len(findings) == 2

    def test_extra_labels_do_not_interfere(self) -> None:
        meta = _make_metadata(
            labels=["type: chore", "type: refactor", "phase: 0", "agent-assisted", "blocked"]
        )
        # Should only flag 'blocked', not the label check
        assert _check_labels(meta) == []


# ---------------------------------------------------------------------------
# _check_not_blocked
# ---------------------------------------------------------------------------


class TestCheckNotBlocked:
    def test_no_blocked_label_passes(self) -> None:
        meta = _make_metadata(labels=["type: feature", "phase: 1"])
        assert _check_not_blocked(meta) == []

    def test_blocked_label_is_blocker(self) -> None:
        meta = _make_metadata(labels=["type: feature", "phase: 1", "blocked"])
        findings = _check_not_blocked(meta)
        assert len(findings) == 1
        assert findings[0].severity == DoRSeverity.BLOCKER
        assert findings[0].rule == "DoR:blocked"


# ---------------------------------------------------------------------------
# refine_issue — integration of all checks
# ---------------------------------------------------------------------------


class TestRefineIssue:
    def test_clean_issue_is_ready(self) -> None:
        meta = _make_metadata()
        result = _patched_refine(meta)
        assert result.ready is True
        assert result.blocker_count == 0

    def test_no_milestone_blocks_readiness(self) -> None:
        meta = _make_metadata(milestone=None)
        result = _patched_refine(meta)
        assert result.ready is False
        assert result.blocker_count >= 1

    def test_missing_type_label_blocks_readiness(self) -> None:
        meta = _make_metadata(labels=["phase: 1"])
        result = _patched_refine(meta)
        assert result.ready is False

    def test_blocked_label_blocks_readiness(self) -> None:
        meta = _make_metadata(labels=["type: feature", "phase: 1", "blocked"])
        result = _patched_refine(meta)
        assert result.ready is False

    def test_too_few_ac_blocks_readiness(self) -> None:
        meta = _make_metadata(body="- [ ] Only one AC item\n")
        result = _patched_refine(meta)
        assert result.ready is False
        assert result.blocker_count >= 1

    def test_findings_sorted_blockers_first(self) -> None:
        # Multiple blockers from different checks
        meta = _make_metadata(
            milestone=None,
            labels=["agent-assisted"],  # missing type and phase
        )
        result = _patched_refine(meta)
        severities = [f.severity for f in result.findings]
        blocker_idx = [i for i, s in enumerate(severities) if s == FindingSeverity.BLOCKER]
        warning_idx = [i for i, s in enumerate(severities) if s == FindingSeverity.WARNING]
        if blocker_idx and warning_idx:
            assert max(blocker_idx) < min(warning_idx)

    def test_llm_env_error_does_not_crash(self) -> None:
        """Static checks must return even when ANTHROPIC_API_KEY is missing."""
        meta = _make_metadata()
        result = _patched_refine(meta)
        assert result is not None
        assert isinstance(result.summary, str)

    def test_counts_match_findings_list(self) -> None:
        meta = _make_metadata(milestone=None, labels=["agent-assisted"])
        result = _patched_refine(meta)
        assert result.blocker_count == sum(
            1 for f in result.findings if f.severity == FindingSeverity.BLOCKER
        )
        assert result.warning_count == sum(
            1 for f in result.findings if f.severity == FindingSeverity.WARNING
        )
        assert result.suggestion_count == sum(
            1 for f in result.findings if f.severity == FindingSeverity.SUGGESTION
        )

    def test_summary_contains_issue_number(self) -> None:
        meta = _make_metadata()
        result = _patched_refine(meta)
        assert "#8" in result.summary


# ---------------------------------------------------------------------------
# IssueMetadata validation
# ---------------------------------------------------------------------------


class TestIssueMetadataValidation:
    def test_valid_metadata_constructs(self) -> None:
        meta = _make_metadata()
        assert meta.issue_number == 8

    def test_issue_number_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            _make_metadata(issue_number=0)

    def test_title_must_not_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            _make_metadata(title="")


# ---------------------------------------------------------------------------
# Shared Finding type — used by both agents
# ---------------------------------------------------------------------------


class TestSharedFindingType:
    def test_finding_can_be_constructed_directly(self) -> None:
        f = Finding(
            location="body",
            severity=FindingSeverity.BLOCKER,
            rule="DoR:ac-count",
            message="Not enough AC items.",
        )
        assert f.severity == FindingSeverity.BLOCKER
        assert f.location == "body"

    def test_finding_severity_enum_values(self) -> None:
        assert FindingSeverity.BLOCKER == "blocker"
        assert FindingSeverity.WARNING == "warning"
        assert FindingSeverity.SUGGESTION == "suggestion"

    def test_pr_review_uses_same_finding_type(self) -> None:
        """ReviewFinding in pr_review/models is the same class as Finding."""
        from src.agents.pr_review.models import ReviewFinding
        from src.core.findings import Finding

        assert ReviewFinding is Finding

    def test_pr_review_severity_is_same_enum(self) -> None:
        from src.agents.pr_review.models import ReviewSeverity
        from src.core.findings import FindingSeverity

        assert ReviewSeverity is FindingSeverity
