#!/usr/bin/env python3
"""
run_pr_review.py — CLI runner for the PR Review Agent.

Usage (local):
    python scripts/run_pr_review.py --pr 42

Usage (CI — called by .github/workflows/pr-review.yml):
    python scripts/run_pr_review.py --pr $PR_NUMBER --post-comment

Behaviour:
  1. Fetches PR metadata + diff via `gh pr view` and `gh pr diff`
  2. Constructs a validated PRMetadata object
  3. Calls review_pull_request() → PRReviewResult
  4. Prints a formatted summary to stdout
  5. If --post-comment: posts findings as a PR comment via `gh pr comment`
  6. Exits 1 only if a deterministic check finds a BLOCKER (fails CI); an LLM outage or
     LLM-reported blockers never fail the job

Environment variables:
    LLM_PROVIDER        defaults to "anthropic"
    ANTHROPIC_API_KEY   required for LLM-assisted review
    GH_TOKEN / GITHUB_TOKEN  required for gh CLI authentication in CI
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
import subprocess
import sys

from tools.agents.pr_review.models import PRMetadata, ReviewSeverity
from tools.agents.pr_review.pr_review_agent import review_pull_request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

_COMMENT_MARKER = "<!-- pr-review-agent -->"
_COMMENT_HEADER = f"{_COMMENT_MARKER}\n## PR Review Agent\n\n"
_MAX_COMMENT_CHARS = 60000  # GitHub rejects comment bodies over 65536 characters
_SEVERITY_EMOJI = {
    ReviewSeverity.BLOCKER: "🚫",
    ReviewSeverity.WARNING: "⚠️",
    ReviewSeverity.SUGGESTION: "💡",
}


def _run(cmd: list[str], check: bool = True) -> str:
    """
    Run a subprocess command and return its stdout as a string.

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


def fetch_pr_metadata(pr_number: int) -> PRMetadata:
    """
    Fetch PR metadata and diff from the GitHub CLI.

    Args:
        pr_number: GitHub PR number to review.

    Returns:
        Validated PRMetadata instance.

    Raises:
        subprocess.CalledProcessError: If gh CLI calls fail.
        pydantic.ValidationError: If the returned data fails model validation.
    """
    logger.info("Fetching PR #%d metadata via gh CLI...", pr_number)

    # Fetch structured metadata as JSON
    meta_json = _run(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "number,title,body,baseRefName,headRefName,author,files,createdAt",
        ]
    )
    meta = json.loads(meta_json)

    # Fetch the unified diff
    try:
        diff = _run(["gh", "pr", "diff", str(pr_number)])
    except subprocess.CalledProcessError:
        logger.warning("Could not fetch diff for PR #%d — proceeding without it.", pr_number)
        diff = ""

    changed_files: list[str] = [f["path"] for f in meta.get("files", [])]

    return PRMetadata(
        pr_number=meta["number"],
        title=meta["title"],
        body=meta.get("body") or "",
        base_branch=meta["baseRefName"],
        head_branch=meta["headRefName"],
        author=meta["author"]["login"],
        changed_files=changed_files,
        diff=diff,
        created_at=datetime.fromisoformat(meta["createdAt"].replace("Z", "+00:00")),
    )


def format_comment(
    result_summary: str,
    findings_md: str,
    approved: bool,
    *,
    coverage_notes: list[str] | None = None,
    llm_unavailable_reason: str | None = None,
) -> str:
    """
    Build the PR comment body from review results.

    Args:
        result_summary: One-paragraph summary string from PRReviewResult.
        findings_md: Markdown-formatted findings table.
        approved: Whether the PR passed with no blockers.
        coverage_notes: What the LLM pass did not review (excluded, truncated, failed).
        llm_unavailable_reason: Set when the LLM review failed; only deterministic
            checks are complete.

    Returns:
        Full comment body as a markdown string, starting with the hidden marker
        used to find and update this comment on later runs.
    """
    if not approved:
        status_line = "**Status: 🚫 Blockers found — must be resolved before merge**"
    elif llm_unavailable_reason:
        status_line = (
            "**Status: ✅ No blockers from deterministic checks "
            "(LLM review incomplete — human approval required)**"
        )
    else:
        status_line = "**Status: ✅ No blockers — eligible for merge (human approval required)**"

    sections = [f"{_COMMENT_HEADER}{status_line}", result_summary]
    if llm_unavailable_reason:
        sections.append(
            f"⚠️ **LLM review unavailable:** {llm_unavailable_reason}. "
            "Only deterministic checks (branch name, target branch, imports, type hints) ran."
        )
    sections.append(findings_md)
    if coverage_notes:
        sections.append(
            "**Review coverage:**\n" + "\n".join(f"- {note}" for note in coverage_notes)
        )
    sections.append("---\n*Generated by PR Review Agent — [source](tools/agents/pr_review/)*")
    return "\n\n".join(sections)[:_MAX_COMMENT_CHARS]


def findings_to_markdown(result: PRReviewResult) -> str:  # type: ignore[name-defined]  # noqa: F821
    """
    Render PRReviewResult findings as a markdown table.

    Args:
        result: Completed PRReviewResult from review_pull_request().

    Returns:
        Markdown string; empty string if there are no findings.
    """

    if not result.findings:
        return "_No findings._"

    lines = [
        "| Severity | File | Rule | Message |",
        "|----------|------|------|---------|",
    ]
    for f in result.findings:
        emoji = _SEVERITY_EMOJI.get(f.severity, "")
        loc = f.location
        if f.line_number:
            loc = f"{loc}:{f.line_number}"
        msg = f.message.replace("|", "\\|")
        if f.suggestion:
            msg += f" _{f.suggestion.replace('|', chr(92) + '|')}_"
        lines.append(f"| {emoji} {f.severity.value} | `{loc}` | `{f.rule}` | {msg} |")

    return "\n".join(lines)


def _find_existing_comment_id(pr_number: int) -> str | None:
    """
    Return the id of the newest PR comment carrying the review marker, or None.

    Args:
        pr_number: GitHub PR number.

    Raises:
        subprocess.CalledProcessError: If the gh API call fails.
    """
    output = _run(
        [
            "gh",
            "api",
            f"repos/{{owner}}/{{repo}}/issues/{pr_number}/comments",
            "--paginate",
            "--jq",
            f'.[] | select(.body | contains("{_COMMENT_MARKER}")) | .id',
        ]
    )
    ids = [line.strip() for line in output.splitlines() if line.strip()]
    return ids[-1] if ids else None


def post_comment(pr_number: int, body: str) -> None:
    """
    Create the review comment, or update it in place if a previous run left one.

    Falls back to posting a new comment if the lookup or the edit fails (for
    example a token without permission to edit), so a review is never lost.

    Args:
        pr_number: GitHub PR number.
        body: Markdown comment body (must contain the hidden review marker).
    """
    existing_id: str | None = None
    try:
        existing_id = _find_existing_comment_id(pr_number)
    except subprocess.CalledProcessError as exc:
        logger.warning("Could not look up an existing review comment: %s", exc)

    if existing_id:
        logger.info("Updating review comment %s on PR #%d...", existing_id, pr_number)
        try:
            _run(
                [
                    "gh",
                    "api",
                    "-X",
                    "PATCH",
                    f"repos/{{owner}}/{{repo}}/issues/comments/{existing_id}",
                    "-f",
                    f"body={body}",
                ]
            )
            logger.info("Comment %s updated on PR #%d.", existing_id, pr_number)
            return
        except subprocess.CalledProcessError as exc:
            logger.warning("Could not update comment %s (%s); posting a new one.", existing_id, exc)

    logger.info("Posting review comment to PR #%d...", pr_number)
    _run(["gh", "pr", "comment", str(pr_number), "--body", body])
    logger.info("Comment posted to PR #%d.", pr_number)


def main() -> int:
    """
    Entry point for the PR review runner.

    Returns:
        1 if a deterministic check found a BLOCKER (or PR data could not be fetched);
        otherwise 0.
    """
    parser = argparse.ArgumentParser(
        description="Run the PR Review Agent against a GitHub pull request."
    )
    parser.add_argument(
        "--pr",
        type=int,
        required=True,
        metavar="NUMBER",
        help="GitHub PR number to review",
    )
    parser.add_argument(
        "--post-comment",
        action="store_true",
        help="Post findings as a PR comment via gh CLI",
    )
    args = parser.parse_args()

    # Fetch PR data
    try:
        metadata = fetch_pr_metadata(args.pr)
    except Exception as exc:
        logger.error("Failed to fetch PR #%d metadata: %s", args.pr, exc)
        return 1

    # Run review
    result = review_pull_request(metadata)

    # Log summary via logger
    logger.info("%s", "\n" + "=" * 70)
    logger.info(
        "PR #%d Review — %s",
        result.pr_number,
        result.reviewed_at.strftime("%Y-%m-%d %H:%M UTC"),
    )
    logger.info("%s", "=" * 70)
    logger.info(result.summary)

    if result.findings:
        logger.info("Findings (%d):", len(result.findings))
        for f in result.findings:
            emoji = _SEVERITY_EMOJI.get(f.severity, "")
            loc = f.location + (f":{f.line_number}" if f.line_number else "")
            logger.info("  %s [%s] %s @ %s", emoji, f.severity.value.upper(), f.rule, loc)
            logger.info("     %s", f.message)
            if f.suggestion:
                logger.info("     → %s", f.suggestion)
    else:
        logger.info("No findings.")

    logger.info("%s", "=" * 70 + "\n")

    # Optionally post comment to PR
    if args.post_comment:
        findings_md = findings_to_markdown(result)
        comment_body = format_comment(
            result.summary,
            findings_md,
            result.approved,
            coverage_notes=result.coverage_notes,
            llm_unavailable_reason=result.llm_unavailable_reason,
        )
        try:
            post_comment(args.pr, comment_body)
        except Exception as exc:
            logger.error("Failed to post comment to PR #%d: %s", args.pr, exc)
            # Non-fatal — do not block CI exit code for comment failure

    # Only deterministic blockers fail CI; LLM-reported blockers show in the status
    # line but leave the merge decision to the human reviewer.
    return 1 if result.static_blocker_count else 0


if __name__ == "__main__":
    sys.exit(main())
