"""
src/core/findings.py

Shared finding types used by all review and quality-gate agents.

Both the PR Review Agent and the Issue Refinement Agent produce findings
using these types. Centralising them here avoids cross-agent imports and
provides a consistent schema for any future lifecycle automation.

Usage:
    from src.core.findings import Finding, FindingSeverity
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class FindingSeverity(StrEnum):
    """Severity level for a single review finding."""

    BLOCKER = "blocker"  # Must be resolved before the gated action proceeds
    WARNING = "warning"  # Should be addressed; reviewer judgment required
    SUGGESTION = "suggestion"  # Optional improvement; low priority


class Finding(BaseModel):
    """
    A single finding produced by any review or quality-gate agent.

    Designed to be generic across PR review, issue refinement, commit
    linting, or any other lifecycle check.
    """

    location: str = Field(
        ...,
        description=(
            "Where the finding applies. For PRs: file path or '(diff line)'. "
            "For issues: field name e.g. 'body', 'labels', 'milestone'. "
            "For commits: 'commit message'."
        ),
    )
    line_number: int | None = Field(
        default=None,
        description="Line number within location, if applicable",
    )
    severity: FindingSeverity
    rule: str = Field(
        ...,
        description=(
            "Short rule identifier. Examples: 'ESOD:no-langchain', "
            "'DoR:ac-count', 'DoR:milestone', 'git-workflow:branch-name'"
        ),
    )
    message: str = Field(..., description="Human-readable explanation of the finding")
    suggestion: str | None = Field(
        default=None,
        description="Optional concrete fix suggestion",
    )
