"""
Pydantic models for the Issue Refinement Agent data boundary (ESOD Section 6).

All issue data fetched from GitHub must be validated through these models
before any DoR check processing.

Finding types are shared with the PR Review Agent via src.core.findings.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.core.findings import Finding, FindingSeverity

# Re-export for convenience and local readability.
DoRSeverity = FindingSeverity
DoRFinding = Finding


class IssueMetadata(BaseModel):
    """
    Validated metadata for a GitHub issue under DoR review.

    Populated from `gh issue view --json` output.
    """

    issue_number: int = Field(..., gt=0, description="GitHub issue number")
    title: str = Field(..., min_length=1, description="Issue title")
    body: str = Field(default="", description="Issue body / description text")
    labels: list[str] = Field(
        default_factory=list,
        description="Label names applied to the issue",
    )
    milestone: str | None = Field(
        default=None,
        description="Milestone name, or None if not assigned",
    )
    assignees: list[str] = Field(
        default_factory=list,
        description="GitHub usernames assigned to the issue",
    )
    created_at: datetime = Field(..., description="UTC timestamp when the issue was opened")
    state: str = Field(default="open", description="Issue state: 'open' or 'closed'")


class IssueRefinementResult(BaseModel):
    """
    Structured output of one issue DoR refinement cycle.

    Consumed by the CLI runner and posted as an issue comment.
    """

    issue_number: int = Field(..., gt=0)
    refined_at: datetime = Field(..., description="UTC timestamp when the refinement completed")
    findings: list[Finding] = Field(
        default_factory=list,
        description="All DoR findings sorted by severity (blockers first)",
    )
    summary: str = Field(
        ...,
        description="One-paragraph narrative summary of DoR status",
    )
    ready: bool = Field(
        ...,
        description="True only when there are zero BLOCKER findings",
    )
    blocker_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    suggestion_count: int = Field(default=0, ge=0)
