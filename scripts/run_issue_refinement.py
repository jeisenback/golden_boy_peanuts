#!/usr/bin/env python3
"""
run_issue_refinement.py — CLI runner for the Issue Refinement Agent.

Usage (local — replaces interactive refine_issue.sh):
    python scripts/run_issue_refinement.py --issue 8

Usage (CI — called by .github/workflows/issue-refinement.yml):
    python scripts/run_issue_refinement.py --issue $ISSUE_NUMBER \
        --post-comment --update-labels

Behaviour:
  1. Fetches IssueMetadata via `gh issue view --json`
  2. Calls refine_issue(metadata) → IssueRefinementResult
  3. Prints a formatted DoR summary to stdout
  4. With --post-comment: posts findings as an issue comment
  5. With --update-labels: removes 'needs-review' if ready; adds 'blocked' if BLOCKERs
  6. Exits 0 if DoR passes (ready=True); exits 1 if any BLOCKERs exist

Environment variables:
    LLM_PROVIDER        defaults to "anthropic"
    ANTHROPIC_API_KEY   required for LLM-assisted DoR check
    GH_TOKEN / GITHUB_TOKEN  required for gh CLI authentication in CI
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
import subprocess
import sys

from src.agents.issue_refinement.issue_refinement_agent import refine_issue
from src.agents.issue_refinement.models import IssueMetadata
from src.core.findings import FindingSeverity

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

_COMMENT_HEADER = "## Issue Refinement Agent (DoR Check)\n\n"
_SEVERITY_EMOJI = {
    FindingSeverity.BLOCKER: "🚫",
    FindingSeverity.WARNING: "⚠️",
    FindingSeverity.SUGGESTION: "💡",
}


def _run(cmd: list[str], check: bool = True) -> str:
    """
    Run a subprocess command and return its stdout.

    Args:
        cmd: Command and arguments list.
        check: If True, raise on non-zero exit code.

    Returns:
        stdout stripped of trailing whitespace.

    Raises:
        subprocess.CalledProcessError: On non-zero exit when check=True.
    """
    result = subprocess.run(cmd, capture_output=True, text=True, check=check)  # noqa: S603
    return result.stdout.strip()


def fetch_issue_metadata(issue_number: int) -> IssueMetadata:
    """
    Fetch issue metadata from the GitHub CLI.

    Args:
        issue_number: GitHub issue number to review.

    Returns:
        Validated IssueMetadata instance.

    Raises:
        subprocess.CalledProcessError: If gh CLI call fails.
        pydantic.ValidationError: If returned data fails model validation.
    """
    logger.info("Fetching issue #%d metadata via gh CLI...", issue_number)

    meta_json = _run(
        [
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--json",
            "number,title,body,labels,milestone,assignees,createdAt,state",
        ]
    )
    meta = json.loads(meta_json)

    labels = [lbl["name"] for lbl in meta.get("labels", [])]
    milestone = meta.get("milestone") or {}
    milestone_name = milestone.get("title") if isinstance(milestone, dict) else None
    assignees = [a["login"] for a in meta.get("assignees", [])]

    return IssueMetadata(
        issue_number=meta["number"],
        title=meta["title"],
        body=meta.get("body") or "",
        labels=labels,
        milestone=milestone_name,
        assignees=assignees,
        created_at=datetime.fromisoformat(meta["createdAt"].replace("Z", "+00:00")),
        state=meta.get("state", "open").lower(),
    )


def findings_to_markdown(result: IssueRefinementResult) -> str:  # type: ignore[name-defined]  # noqa: F821
    """
    Render IssueRefinementResult findings as a markdown table.

    Args:
        result: Completed IssueRefinementResult from refine_issue().

    Returns:
        Markdown string; '_No findings._' if there are none.
    """
    if not result.findings:
        return "_No findings._"

    lines = [
        "| Severity | Location | Rule | Message |",
        "|----------|----------|------|---------|",
    ]
    for f in result.findings:
        emoji = _SEVERITY_EMOJI.get(f.severity, "")
        msg = f.message.replace("|", "\\|")
        if f.suggestion:
            msg += f" _{f.suggestion.replace('|', chr(92) + '|')}_"
        lines.append(f"| {emoji} {f.severity.value} | `{f.location}` | `{f.rule}` | {msg} |")
    return "\n".join(lines)


def format_comment(result: IssueRefinementResult) -> str:  # type: ignore[name-defined]  # noqa: F821
    """
    Build the issue comment body from refinement results.

    Args:
        result: Completed IssueRefinementResult.

    Returns:
        Full comment body as a markdown string.
    """
    status_line = (
        "**Status: ✅ DoR passed — eligible for sprint planning (human approval required)**"
        if result.ready
        else "**Status: 🚫 Not Ready — blockers must be resolved before sprint entry**"
    )
    findings_md = findings_to_markdown(result)
    return (
        f"{_COMMENT_HEADER}"
        f"{status_line}\n\n"
        f"{result.summary}\n\n"
        f"{findings_md}"
        f"\n\n---\n*Generated by Issue Refinement Agent — "
        f"[source](src/agents/issue_refinement/)*"
    )


def post_comment(issue_number: int, body: str) -> None:
    """
    Post a comment to a GitHub issue via the gh CLI.

    Args:
        issue_number: GitHub issue number.
        body: Markdown comment body.
    """
    logger.info("Posting DoR comment to issue #%d...", issue_number)
    _run(["gh", "issue", "comment", str(issue_number), "--body", body])
    logger.info("Comment posted to issue #%d.", issue_number)


def update_labels(issue_number: int, ready: bool) -> None:
    """
    Update GitHub labels based on DoR result.

    Removes 'needs-review' when ready; adds 'blocked' when not ready.

    Args:
        issue_number: GitHub issue number.
        ready: Whether the issue passed DoR.
    """
    if ready:
        logger.info("Issue #%d: DoR passed — removing 'needs-review' label.", issue_number)
        _run(
            ["gh", "issue", "edit", str(issue_number), "--remove-label", "needs-review"],
            check=False,
        )
    else:
        logger.info("Issue #%d: DoR failed — adding 'blocked' label.", issue_number)
        _run(
            ["gh", "issue", "edit", str(issue_number), "--add-label", "blocked"],
            check=False,
        )


def main() -> int:
    """
    Entry point for the issue refinement runner.

    Returns:
        0 if DoR passes (ready=True); 1 if any BLOCKER findings exist.
    """
    parser = argparse.ArgumentParser(
        description="Run the Issue Refinement Agent (DoR check) against a GitHub issue."
    )
    parser.add_argument(
        "--issue",
        type=int,
        required=True,
        metavar="NUMBER",
        help="GitHub issue number to check",
    )
    parser.add_argument(
        "--post-comment",
        action="store_true",
        help="Post findings as an issue comment via gh CLI",
    )
    parser.add_argument(
        "--update-labels",
        action="store_true",
        help=("Update labels: remove 'needs-review' on pass; " "add 'blocked' on BLOCKER findings"),
    )
    args = parser.parse_args()

    # Fetch issue data
    try:
        metadata = fetch_issue_metadata(args.issue)
    except Exception as exc:
        logger.error("Failed to fetch issue #%d metadata: %s", args.issue, exc)
        return 1

    # Run DoR check
    result = refine_issue(metadata)

    # Log summary to stdout via logger
    logger.info("%s", "\n" + "=" * 70)
    logger.info(
        "Issue #%d DoR Check — %s",
        result.issue_number,
        result.refined_at.strftime("%Y-%m-%d %H:%M UTC"),
    )
    logger.info("%s", "=" * 70)
    logger.info(result.summary)

    if result.findings:
        logger.info("Findings (%d):", len(result.findings))
        for f in result.findings:
            emoji = _SEVERITY_EMOJI.get(f.severity, "")
            logger.info("  %s [%s] %s @ %s", emoji, f.severity.value.upper(), f.rule, f.location)
            logger.info("     %s", f.message)
            if f.suggestion:
                logger.info("     → %s", f.suggestion)
    else:
        logger.info("No findings — issue is DoR ready.")

    logger.info("%s", "=" * 70 + "\n")

    # Optionally post comment and update labels
    if args.post_comment:
        try:
            post_comment(args.issue, format_comment(result))
        except Exception as exc:
            logger.error("Failed to post comment to issue #%d: %s", args.issue, exc)

    if args.update_labels:
        try:
            update_labels(args.issue, result.ready)
        except Exception as exc:
            logger.error("Failed to update labels for issue #%d: %s", args.issue, exc)

    return 0 if result.ready else 1


if __name__ == "__main__":
    sys.exit(main())
