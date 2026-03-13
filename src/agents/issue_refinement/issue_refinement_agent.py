"""
Issue Refinement Agent

Responsibilities:
  - Accept an IssueMetadata object describing a GitHub issue
  - Apply static DoR checks (AC count, milestone, labels, blocked state)
  - Delegate narrative quality review to LLMWrapper (via src.core.llm_wrapper)
  - Produce a structured IssueRefinementResult with ranked findings
  - Mark ready=True only when there are zero BLOCKER findings

Static DoR checks enforced (no LLM required) — from docs/sprint_framework.md § 3:
  - Issue body contains ≥ 3 checkbox AC items (- [ ] ...)
  - Milestone is assigned
  - At least one type:* label is present
  - At least one phase:* label is present
  - No 'blocked' label is present

LLM-assisted checks (via LLMWrapper):
  - Are AC items specific and testable (not vague)?
  - Is the title a clear single-sentence goal stating what 'done' looks like?
  - Is the scope narrow enough for a single sprint issue?

ESOD constraints: Python 3.11+, type hints on all public functions,
no langchain.*/langgraph.* imports, LLM calls via LLMWrapper only.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from src.agents.issue_refinement.models import (
    DoRFinding,
    DoRSeverity,
    IssueMetadata,
    IssueRefinementResult,
)
from src.core.llm_wrapper import LLMWrapper

logger = logging.getLogger(__name__)

# Minimum number of checkbox AC items required in the issue body (DoR item 2)
_MIN_AC_COUNT = 3

# Regex: matches a GitHub-flavoured markdown checkbox task item
_AC_CHECKBOX_RE = re.compile(r"^\s*-\s*\[[ x]\]", re.MULTILINE)

# Label prefix patterns required for DoR (must have one of each)
_TYPE_LABEL_RE = re.compile(r"^type:")
_PHASE_LABEL_RE = re.compile(r"^phase:")

# Model used for LLM-assisted review (LLMWrapper.complete — ESOD Section 5.3)
_REVIEW_MODEL_ID = "claude-sonnet-4-6"

_REVIEW_PROMPT_TEMPLATE = """\
You are a senior engineer reviewing a GitHub issue for the Energy Options Opportunity Agent.
Your job is to assess whether this issue is ready to be picked up in a sprint.

Definition of Ready criteria to evaluate:
1. The title is a clear, single-sentence goal stating what "done" looks like.
2. Each acceptance criterion is specific and testable — not vague or open-ended.
3. The scope is narrow enough to be completed in one sprint (a few days of work).

Issue Title: {title}
Issue Body:
{body}

List only concrete findings. For each finding provide:
- location: the field with the problem (e.g. 'title', 'body', 'AC item 2')
- severity: blocker | warning | suggestion
- rule: short identifier (e.g. 'DoR:ac-vague', 'DoR:title-unclear', 'DoR:scope-too-large')
- message: one sentence explaining the problem
- suggestion: one sentence fix

If the issue looks ready, say "No findings." Do not invent issues.
"""


def _check_ac_count(metadata: IssueMetadata) -> list[DoRFinding]:
    """
    Verify the issue body contains at least _MIN_AC_COUNT checkbox AC items.

    Args:
        metadata: Validated issue metadata.

    Returns:
        BLOCKER finding if fewer than _MIN_AC_COUNT checkboxes found; else empty.
    """
    checkboxes = _AC_CHECKBOX_RE.findall(metadata.body)
    count = len(checkboxes)
    if count < _MIN_AC_COUNT:
        return [
            DoRFinding(
                location="body",
                severity=DoRSeverity.BLOCKER,
                rule="DoR:ac-count",
                message=(
                    f"Issue has {count} checkbox AC item(s); minimum is {_MIN_AC_COUNT}. "
                    "Each AC must be a '- [ ]' checkbox in the issue body."
                ),
                suggestion=(
                    f"Add at least {_MIN_AC_COUNT - count} more specific, testable "
                    "acceptance criteria as '- [ ] ...' checkboxes."
                ),
            )
        ]
    return []


def _check_milestone(metadata: IssueMetadata) -> list[DoRFinding]:
    """
    Verify a milestone is assigned to the issue.

    Args:
        metadata: Validated issue metadata.

    Returns:
        BLOCKER finding if no milestone is set; else empty.
    """
    if not metadata.milestone:
        return [
            DoRFinding(
                location="milestone",
                severity=DoRSeverity.BLOCKER,
                rule="DoR:milestone",
                message=(
                    "No milestone assigned. Issues must be assigned to a phase milestone "
                    "before entering a sprint (DoR item 3)."
                ),
                suggestion=(
                    "Assign a milestone: Phase 0 / Phase 1 / Phase 2 / Phase 3 / Phase 4."
                ),
            )
        ]
    return []


def _check_labels(metadata: IssueMetadata) -> list[DoRFinding]:
    """
    Verify the issue has at least one type:* label and one phase:* label.

    Args:
        metadata: Validated issue metadata.

    Returns:
        One BLOCKER finding per missing label category; empty if compliant.
    """
    findings: list[DoRFinding] = []
    has_type = any(_TYPE_LABEL_RE.match(lbl) for lbl in metadata.labels)
    has_phase = any(_PHASE_LABEL_RE.match(lbl) for lbl in metadata.labels)

    if not has_type:
        findings.append(
            DoRFinding(
                location="labels",
                severity=DoRSeverity.BLOCKER,
                rule="DoR:label-type",
                message=(
                    "No 'type:*' label present. Issues must have at least one type label "
                    "(e.g. 'type: feature', 'type: fix') — DoR item 4."
                ),
                suggestion="Add a type label via the GitHub issue sidebar.",
            )
        )
    if not has_phase:
        findings.append(
            DoRFinding(
                location="labels",
                severity=DoRSeverity.BLOCKER,
                rule="DoR:label-phase",
                message=(
                    "No 'phase:*' label present. Issues must have at least one phase label "
                    "(e.g. 'phase: 0', 'phase: 1') — DoR item 4."
                ),
                suggestion="Add a phase label via the GitHub issue sidebar.",
            )
        )
    return findings


def _check_not_blocked(metadata: IssueMetadata) -> list[DoRFinding]:
    """
    Verify the issue does not carry the 'blocked' label.

    Args:
        metadata: Validated issue metadata.

    Returns:
        BLOCKER finding if 'blocked' label is present; else empty.
    """
    if "blocked" in metadata.labels:
        return [
            DoRFinding(
                location="labels",
                severity=DoRSeverity.BLOCKER,
                rule="DoR:blocked",
                message=(
                    "Issue is labelled 'blocked'. Blocked issues cannot enter a sprint "
                    "until the blocker is resolved (DoR item 5)."
                ),
                suggestion=(
                    "Resolve the blocker, remove the 'blocked' label, "
                    "and document the resolution in the issue body."
                ),
            )
        ]
    return []


def _parse_llm_findings(llm_text: str, issue_number: int) -> list[DoRFinding]:
    """
    Parse LLM narrative output into DoRFinding objects.

    Unstructured LLM text is returned as a single SUGGESTION finding so
    nothing is silently dropped. A future issue will add JSON schema output.

    Args:
        llm_text: Raw text from LLMWrapper.complete().
        issue_number: Issue number for logging context.

    Returns:
        List of DoRFinding parsed from llm_text.
    """
    if llm_text.strip().lower().startswith("no findings"):
        logger.info("Issue #%d: LLM DoR review returned no findings.", issue_number)
        return []

    return [
        DoRFinding(
            location="(llm-review)",
            severity=DoRSeverity.SUGGESTION,
            rule="llm:dor-narrative",
            message=llm_text.strip()[:2000],
            suggestion=None,
        )
    ]


def _tally(findings: list[DoRFinding]) -> tuple[int, int, int]:
    """
    Count findings by severity.

    Args:
        findings: All findings from a refinement pass.

    Returns:
        Tuple of (blocker_count, warning_count, suggestion_count).
    """
    blockers = sum(1 for f in findings if f.severity == DoRSeverity.BLOCKER)
    warnings = sum(1 for f in findings if f.severity == DoRSeverity.WARNING)
    suggestions = sum(1 for f in findings if f.severity == DoRSeverity.SUGGESTION)
    return blockers, warnings, suggestions


def refine_issue(
    metadata: IssueMetadata,
    model_id: str = _REVIEW_MODEL_ID,
) -> IssueRefinementResult:
    """
    Execute a full DoR refinement cycle and return a structured result.

    Steps:
      1. Run all static DoR checks (AC count, milestone, labels, blocked state).
      2. Delegate narrative quality review to LLMWrapper.
      3. Aggregate findings, tally severities, and set ready = (blockers == 0).

    Args:
        metadata: Validated IssueMetadata for the issue under review.
        model_id: LLM model identifier to use for narrative review.
                  Defaults to the module-level _REVIEW_MODEL_ID constant.

    Returns:
        IssueRefinementResult with findings sorted by severity and a ready flag.
    """
    logger.info(
        "Starting DoR refinement for issue #%d: '%s'",
        metadata.issue_number,
        metadata.title,
    )

    findings: list[DoRFinding] = []

    # --- Static DoR checks (no LLM required) ---
    findings.extend(_check_ac_count(metadata))
    findings.extend(_check_milestone(metadata))
    findings.extend(_check_labels(metadata))
    findings.extend(_check_not_blocked(metadata))

    logger.info(
        "Issue #%d: static DoR checks complete — %d findings so far.",
        metadata.issue_number,
        len(findings),
    )

    # --- LLM-assisted narrative review ---
    wrapper = LLMWrapper(model_id=model_id)
    prompt = _REVIEW_PROMPT_TEMPLATE.format(
        title=metadata.title,
        body=metadata.body[:8000],  # Truncate very long bodies
    )
    try:
        response = wrapper.complete(prompt=prompt)
        llm_findings = _parse_llm_findings(response.content, metadata.issue_number)
        findings.extend(llm_findings)
        logger.info(
            "Issue #%d: LLM review added %d findings.",
            metadata.issue_number,
            len(llm_findings),
        )
    except (NotImplementedError, EnvironmentError) as exc:
        logger.warning(
            "Issue #%d: LLM review unavailable (%s) — static checks still apply.",
            metadata.issue_number,
            exc,
        )

    # Sort: blockers first, then warnings, then suggestions
    severity_order = {
        DoRSeverity.BLOCKER: 0,
        DoRSeverity.WARNING: 1,
        DoRSeverity.SUGGESTION: 2,
    }
    findings.sort(key=lambda f: severity_order[f.severity])

    blocker_count, warning_count, suggestion_count = _tally(findings)
    ready = blocker_count == 0

    summary_parts = [
        f"Issue #{metadata.issue_number} '{metadata.title}' DoR check complete.",
        f"Findings: {blocker_count} blocker(s), {warning_count} warning(s), "
        f"{suggestion_count} suggestion(s).",
    ]
    if ready:
        summary_parts.append(
            "No blockers — issue is eligible for sprint planning (human approval required)."
        )
    else:
        summary_parts.append(
            f"{blocker_count} blocker(s) must be resolved before this issue can enter a sprint."
        )

    result = IssueRefinementResult(
        issue_number=metadata.issue_number,
        refined_at=datetime.now(tz=timezone.utc),
        findings=findings,
        summary=" ".join(summary_parts),
        ready=ready,
        blocker_count=blocker_count,
        warning_count=warning_count,
        suggestion_count=suggestion_count,
    )

    logger.info(
        "Issue #%d refinement finished. ready=%s blockers=%d warnings=%d suggestions=%d",
        metadata.issue_number,
        result.ready,
        result.blocker_count,
        result.warning_count,
        result.suggestion_count,
    )
    return result
