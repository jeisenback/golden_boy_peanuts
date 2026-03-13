"""
Pydantic models for the PR Review Agent data boundary (ESOD Section 6).

All PR data ingested from GitHub must be validated through these models
before any LLM-based review processing.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ReviewSeverity(StrEnum):
    """Severity level for a single review finding."""

    BLOCKER = "blocker"       # Must be fixed before merge (ESOD violation, test missing)
    WARNING = "warning"       # Should be addressed; reviewer judgment required
    SUGGESTION = "suggestion" # Optional improvement; low priority


class ReviewFinding(BaseModel):
    """
    Single finding produced during a PR review pass.

    Each finding maps to one or more changed lines and cites the
    ESOD / code standard rule that was evaluated.
    """

    file_path: str = Field(..., description="Relative path of the file containing the finding")
    line_number: int | None = Field(
        default=None,
        description="Line number within file_path, if applicable",
    )
    severity: ReviewSeverity
    rule: str = Field(
        ...,
        description=(
            "Short rule identifier, e.g. 'ESOD:no-langchain', "
            "'ESOD:type-hints', 'ESOD:pydantic-boundary', 'commit-format'"
        ),
    )
    message: str = Field(..., description="Human-readable explanation of the finding")
    suggestion: str | None = Field(
        default=None,
        description="Optional concrete fix suggestion for the author",
    )


class PRMetadata(BaseModel):
    """
    Validated metadata for a pull request under review.

    Populated from the GitHub API or locally via `gh pr view`.
    """

    pr_number: int = Field(..., gt=0, description="GitHub PR number")
    title: str = Field(..., min_length=1, description="PR title")
    body: str = Field(default="", description="PR description / body text")
    base_branch: str = Field(..., description="Target branch, e.g. 'develop'")
    head_branch: str = Field(..., description="Source branch, e.g. 'feature/8-fetch-crude-prices'")
    author: str = Field(..., description="GitHub username of the PR author")
    changed_files: list[str] = Field(
        default_factory=list,
        description="List of file paths changed in this PR",
    )
    diff: str = Field(
        default="",
        description="Unified diff of the entire PR. May be empty for very large PRs.",
    )
    created_at: datetime = Field(..., description="UTC timestamp when the PR was opened")


class PRReviewResult(BaseModel):
    """
    Structured output of one PR review cycle.

    Consumed by the CI comment step and displayed to the human reviewer.
    """

    pr_number: int = Field(..., gt=0)
    reviewed_at: datetime = Field(..., description="UTC timestamp when the review completed")
    findings: list[ReviewFinding] = Field(
        default_factory=list,
        description="All findings sorted by severity (blockers first)",
    )
    summary: str = Field(
        ...,
        description="One-paragraph narrative summary of the overall PR quality",
    )
    approved: bool = Field(
        ...,
        description=(
            "True only when there are zero BLOCKER findings and "
            "the PR meets all ESOD hard constraints"
        ),
    )
    blocker_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    suggestion_count: int = Field(default=0, ge=0)
