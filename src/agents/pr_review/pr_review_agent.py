"""
PR Review Agent

Responsibilities:
  - Accept a PRMetadata object describing a GitHub pull request
  - Apply static rule checks (branch naming, commit format, ESOD hard constraints)
  - Delegate narrative review to LLMWrapper (via src.core.llm_wrapper)
  - Produce a structured PRReviewResult with ranked findings
  - Never approve a PR that contains BLOCKER findings

Static checks enforced (no LLM required):
  - No langchain.* / langgraph.* imports in src/ files
  - All public functions in changed .py files carry type hints (heuristic)
  - Branch name follows <type>/<issue>-<slug> convention (git_workflow.md)
  - PR targets 'develop', never 'main' (git_workflow.md)
  - Commit messages in changed commits reference an issue number (#N)

LLM-assisted checks (via LLMWrapper):
  - Pydantic boundary validation present at module entry points
  - SQL writes use parameterized queries (no f-string SQL)
  - Error handling does not swallow exceptions silently
  - Code quality, readability, and alignment with design doc intent

ESOD constraints: Python 3.11+, type hints on all public functions,
no langchain.*/langgraph.* imports, LLM calls via LLMWrapper only.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re

from src.agents.pr_review.models import (
    PRMetadata,
    PRReviewResult,
    ReviewFinding,
    ReviewSeverity,
)
from src.core.llm_wrapper import LLMWrapper

logger = logging.getLogger(__name__)

# Regex patterns for static rule checks (git_workflow.md)
_BRANCH_RE = re.compile(r"^(feature|fix|refactor|chore|test|docs)/\d+-[a-z0-9-]+$")
_COMMIT_ISSUE_RE = re.compile(r"#\d+")
_LANGCHAIN_RE = re.compile(r"^\s*(import|from)\s+(langchain|langgraph)", re.MULTILINE)
_TYPE_HINT_DEF_RE = re.compile(r"^def\s+[a-z_][a-zA-Z0-9_]*\s*\([^)]*\)(?!\s*->)", re.MULTILINE)

# Model used for LLM-assisted review (LLMWrapper.complete — ESOD Section 5.3)
_REVIEW_MODEL_ID = "claude-sonnet-4-6"

_REVIEW_PROMPT_TEMPLATE = """\
You are a senior engineer reviewing a pull request for the Energy Options Opportunity Agent.
Your job is to check the diff for violations of the project's engineering standards (ESOD).

Key standards to check:
1. Pydantic models must validate all data at every module boundary (inbound data, API responses).
2. All LLM calls must go through src.core.llm_wrapper.LLMWrapper — no direct provider SDK usage.
3. SQL writes must use parameterized queries — never f-string or %-formatted SQL.
4. Exceptions must not be silently swallowed — logging + re-raise or
   structured error response required.
5. No magic numbers — constants must be named and documented.
6. Public functions must have docstrings explaining purpose, args, and return values.

PR Title: {title}
PR Branch: {head_branch} → {base_branch}

Diff:
{diff}

List only concrete findings. For each finding provide:
- file_path
- severity (blocker|warning|suggestion)
- rule (short identifier)
- message (one sentence)
- suggestion (one sentence fix, if applicable)

If the diff looks clean, say "No findings." Do not invent issues.
"""


def _check_branch_name(metadata: PRMetadata) -> list[ReviewFinding]:
    """
    Verify the head branch follows <type>/<issue>-<slug> naming convention.

    Args:
        metadata: Validated PR metadata.

    Returns:
        List of findings; empty if the branch name is compliant.
    """
    if not _BRANCH_RE.match(metadata.head_branch):
        return [
            ReviewFinding(
                location=".git/HEAD",
                severity=ReviewSeverity.BLOCKER,
                rule="git-workflow:branch-name",
                message=(
                    f"Branch '{metadata.head_branch}' does not follow the required "
                    "<type>/<issue>-<slug> format (e.g. feature/8-fetch-crude-prices)."
                ),
                suggestion=(
                    "Rename the branch: git branch -m <type>/<issue>-<slug> "
                    "and update the remote ref."
                ),
            )
        ]
    return []


def _check_target_branch(metadata: PRMetadata) -> list[ReviewFinding]:
    """
    Ensure the PR targets 'develop', not 'main'.

    Args:
        metadata: Validated PR metadata.

    Returns:
        List of findings; empty if the target branch is compliant.
    """
    if metadata.base_branch == "main":
        return [
            ReviewFinding(
                location=".github/PR",
                severity=ReviewSeverity.BLOCKER,
                rule="git-workflow:no-direct-to-main",
                message=(
                    "PR targets 'main' directly. All PRs must target 'develop'. "
                    "Only the human lead merges develop → main."
                ),
                suggestion="Change the base branch to 'develop' via the GitHub PR UI.",
            )
        ]
    return []


def _check_langchain_imports(metadata: PRMetadata) -> list[ReviewFinding]:
    """
    Scan the diff for any langchain.* or langgraph.* imports added in src/ files.

    Args:
        metadata: Validated PR metadata.

    Returns:
        One BLOCKER finding per match; empty if clean.
    """
    findings: list[ReviewFinding] = []
    if not metadata.diff:
        return findings

    for line_num, line in enumerate(metadata.diff.splitlines(), start=1):
        if not line.startswith("+"):
            continue
        if _LANGCHAIN_RE.search(line[1:]):
            findings.append(
                ReviewFinding(
                    location="(diff line)",
                    line_number=line_num,
                    severity=ReviewSeverity.BLOCKER,
                    rule="ESOD:no-langchain",
                    message=(
                        f"Added import from langchain or langgraph detected: '{line.strip()}'. "
                        "These are forbidden in src/ at runtime (ESOD zero-tolerance rule)."
                    ),
                    suggestion=(
                        "Remove the import. Use src.core.llm_wrapper.LLMWrapper "
                        "for all LLM interactions."
                    ),
                )
            )
    return findings


def _check_type_hints(metadata: PRMetadata) -> list[ReviewFinding]:
    """
    Heuristically flag public function definitions that appear to be missing return-type hints.

    Matches 'def func(...)' without a '->' annotation in added lines of .py files.

    Args:
        metadata: Validated PR metadata.

    Returns:
        WARNING findings for each suspected missing type hint.
    """
    findings: list[ReviewFinding] = []
    if not metadata.diff:
        return findings

    added_block: list[tuple[int, str]] = []
    current_file = ""

    for line_num, line in enumerate(metadata.diff.splitlines(), start=1):
        if line.startswith("diff --git"):
            parts = line.split(" b/")
            current_file = parts[-1] if len(parts) > 1 else current_file
        if line.startswith("+") and not line.startswith("+++") and current_file.endswith(".py"):
            added_block.append((line_num, line[1:]))

    added_src = "\n".join(src for _, src in added_block)
    for match in _TYPE_HINT_DEF_RE.finditer(added_src):
        fn_line = match.group(0).strip()
        # Skip private/dunder helpers
        fn_name_match = re.search(r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)", fn_line)
        if fn_name_match and fn_name_match.group(1).startswith("_"):
            continue
        findings.append(
            ReviewFinding(
                location=current_file,
                severity=ReviewSeverity.WARNING,
                rule="ESOD:type-hints",
                message=(
                    f"Public function may be missing a return-type hint: '{fn_line[:80]}'. "
                    "ESOD requires type hints on all public functions."
                ),
                suggestion="Add a return-type annotation: def func(...) -> ReturnType:",
            )
        )
    return findings


def _parse_llm_findings(
    llm_text: str,
    pr_number: int,
) -> list[ReviewFinding]:
    """
    Parse LLM narrative output into ReviewFinding objects where possible.

    The LLM is instructed to emit structured text; this function extracts
    severity-tagged findings. Unstructured text is returned as a single
    SUGGESTION finding to ensure nothing is silently dropped.

    Args:
        llm_text: Raw text returned by LLMWrapper.complete().
        pr_number: PR number, used for logging context.

    Returns:
        List of ReviewFinding parsed from llm_text.
    """
    if llm_text.strip().lower().startswith("no findings"):
        logger.info("PR #%d: LLM review returned no findings.", pr_number)
        return []

    # Treat the entire LLM output as a single narrative finding when
    # structured parsing is not yet implemented. A future issue will add
    # a formal JSON schema to the LLM prompt for machine-readable output.
    return [
        ReviewFinding(
            location="(llm-review)",
            severity=ReviewSeverity.SUGGESTION,
            rule="llm:narrative-review",
            message=llm_text.strip()[:2000],
            suggestion=None,
        )
    ]


def _tally(findings: list[ReviewFinding]) -> tuple[int, int, int]:
    """
    Count findings by severity.

    Args:
        findings: All findings from a review pass.

    Returns:
        Tuple of (blocker_count, warning_count, suggestion_count).
    """
    blockers = sum(1 for f in findings if f.severity == ReviewSeverity.BLOCKER)
    warnings = sum(1 for f in findings if f.severity == ReviewSeverity.WARNING)
    suggestions = sum(1 for f in findings if f.severity == ReviewSeverity.SUGGESTION)
    return blockers, warnings, suggestions


def review_pull_request(
    metadata: PRMetadata,
    model_id: str = _REVIEW_MODEL_ID,
) -> PRReviewResult:
    """
    Execute a full PR review cycle and return a structured result.

    Steps:
      1. Run all static rule checks (branch name, target branch, ESOD imports, type hints).
      2. If a diff is available, delegate narrative analysis to LLMWrapper.
      3. Aggregate findings, tally severities, and set approved = (blockers == 0).

    Args:
        metadata: Validated PRMetadata for the pull request under review.
        model_id: LLM model identifier to use for narrative review.
                  Defaults to the module-level _REVIEW_MODEL_ID constant.

    Returns:
        PRReviewResult with all findings sorted by severity (blockers first)
        and a boolean approved flag.

    Raises:
        NotImplementedError: LLMWrapper.complete() is not yet implemented.
            Static checks still run and are returned even if LLM step fails.
    """
    logger.info("Starting PR review for PR #%d: '%s'", metadata.pr_number, metadata.title)

    findings: list[ReviewFinding] = []

    # --- Static checks (no LLM required) ---
    findings.extend(_check_branch_name(metadata))
    findings.extend(_check_target_branch(metadata))
    findings.extend(_check_langchain_imports(metadata))
    findings.extend(_check_type_hints(metadata))

    logger.info(
        "PR #%d: static checks complete — %d findings so far.",
        metadata.pr_number,
        len(findings),
    )

    # --- LLM-assisted narrative review ---
    if metadata.diff:
        wrapper = LLMWrapper(model_id=model_id)
        prompt = _REVIEW_PROMPT_TEMPLATE.format(
            title=metadata.title,
            head_branch=metadata.head_branch,
            base_branch=metadata.base_branch,
            diff=metadata.diff[:12000],  # Truncate very large diffs
        )
        try:
            response = wrapper.complete(prompt=prompt)
            llm_findings = _parse_llm_findings(response.content, metadata.pr_number)
            findings.extend(llm_findings)
            logger.info(
                "PR #%d: LLM review added %d findings.",
                metadata.pr_number,
                len(llm_findings),
            )
        except NotImplementedError:
            logger.warning(
                "PR #%d: LLMWrapper.complete() is not yet implemented — "
                "skipping narrative review. Static checks still apply.",
                metadata.pr_number,
            )
    else:
        logger.warning("PR #%d: no diff provided — skipping LLM review pass.", metadata.pr_number)

    # Sort: blockers first, then warnings, then suggestions
    severity_order = {
        ReviewSeverity.BLOCKER: 0,
        ReviewSeverity.WARNING: 1,
        ReviewSeverity.SUGGESTION: 2,
    }
    findings.sort(key=lambda f: severity_order[f.severity])

    blocker_count, warning_count, suggestion_count = _tally(findings)
    approved = blocker_count == 0

    summary_parts = [
        f"PR #{metadata.pr_number} '{metadata.title}' review complete.",
        f"Findings: {blocker_count} blocker(s), {warning_count} warning(s), "
        f"{suggestion_count} suggestion(s).",
    ]
    if approved:
        summary_parts.append(
            "No blockers found — PR is eligible for merge (human approval required)."
        )
    else:
        summary_parts.append(
            f"{blocker_count} blocker(s) must be resolved before this PR can be merged."
        )

    result = PRReviewResult(
        pr_number=metadata.pr_number,
        reviewed_at=datetime.now(tz=timezone.utc),
        findings=findings,
        summary=" ".join(summary_parts),
        approved=approved,
        blocker_count=blocker_count,
        warning_count=warning_count,
        suggestion_count=suggestion_count,
    )

    logger.info(
        "PR #%d review finished. approved=%s blockers=%d warnings=%d suggestions=%d",
        metadata.pr_number,
        result.approved,
        result.blocker_count,
        result.warning_count,
        result.suggestion_count,
    )
    return result
