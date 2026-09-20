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

from datetime import UTC, datetime
import json
import logging
import re

from pydantic import BaseModel, Field, ValidationError

from src.core.llm_wrapper import LLMWrapper
from tools.agents.pr_review.models import (
    PRMetadata,
    PRReviewResult,
    ReviewFinding,
    ReviewSeverity,
)

logger = logging.getLogger(__name__)

# Regex patterns for static rule checks (git_workflow.md)
_BRANCH_RE = re.compile(r"^(feature|fix|refactor|chore|test|docs|infra)/\d+-[a-z0-9-]+$")
_COMMIT_ISSUE_RE = re.compile(r"#\d+")
_LANGCHAIN_RE = re.compile(r"^\s*(import|from)\s+(langchain|langgraph)", re.MULTILINE)
_TYPE_HINT_DEF_RE = re.compile(r"^def\s+[a-z_][a-zA-Z0-9_]*\s*\([^)]*\)(?!\s*->)", re.MULTILINE)

# Model used for LLM-assisted review (LLMWrapper.complete — ESOD Section 5.3)
_REVIEW_MODEL_ID = "claude-sonnet-4-6"

# Diff budgeting for LLM review. Each chunk is one LLM call; files are packed whole
# where possible so the model never sees half of a file it is asked to judge.
_MAX_CHARS_PER_CHUNK = 12000
_MAX_LLM_CHUNKS = 4
_MAX_UNPARSED_EXCERPT_CHARS = 500
_MAX_FINDING_MESSAGE_CHARS = 2000

# Files that add noise but no reviewable logic: excluded from LLM chunks (static
# checks still see the full diff). Reported in the comment so nothing is hidden.
_EXCLUDED_SUFFIXES = (".csv", ".json", ".lock", ".svg")
_EXCLUDED_PATHS = ("HEARTBEAT.md",)
_EXCLUDED_PREFIXES = ("docs/generated/", "docs/vendor_evaluation/samples/")

# Review order: code that carries the ESOD rules first, so it survives the chunk cap.
_PATH_PRIORITY = ("src/", "tools/", "scripts/", ".github/", "tests/")

_DIFF_FILE_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.MULTILINE)
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

_LLM_RULE_PREFIX = "llm:"

_REVIEW_PROMPT_TEMPLATE = """You are a senior engineer reviewing a PR for the Energy Options Agent.
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
{chunk_info}

Diff:
{diff}

Review ONLY the files shown in this diff. Do not comment on files that are not shown.
Report only concrete findings; do not invent issues.

Respond with ONLY a JSON array (no prose, no code fence). Each element is an object with:
  "file_path": string, "line_number": integer or null,
  "severity": "blocker" | "warning" | "suggestion",
  "rule": short identifier, "message": one sentence,
  "suggestion": one-sentence fix or null
If the diff looks clean, respond with [].
"""


class _LLMFindingPayload(BaseModel):
    """Boundary model for one finding as emitted by the LLM (ESOD Section 6)."""

    file_path: str = Field(default="(llm-review)", min_length=1)
    line_number: int | None = None
    severity: ReviewSeverity
    rule: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    suggestion: str | None = None


def _check_branch_name(metadata: PRMetadata) -> list[ReviewFinding]:
    """
    Verify the head branch follows <type>/<issue>-<slug> naming convention.

    Branches prefixed with 'claude/' are system-assigned session branches
    (see CLAUDE.md) and are exempt from the convention check.

    Args:
        metadata: Validated PR metadata.

    Returns:
        List of findings; empty if the branch name is compliant or exempt.
    """
    if metadata.head_branch.startswith("claude/"):
        return []
    # Protected integration branches are exempt from feature-branch naming.
    if metadata.head_branch in {"develop", "main"}:
        return []
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
    # develop → main is the valid release path; exempt it.
    if metadata.base_branch == "main" and metadata.head_branch == "develop":
        return []
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


def _split_diff_by_file(diff: str) -> list[tuple[str, str]]:
    """
    Split a unified diff into (path, section) pairs, one per changed file.

    Args:
        diff: Unified diff text as produced by `gh pr diff`.

    Returns:
        List of (new-side path, full diff section) in original order. Sections whose
        header cannot be parsed get the path "(unknown)".
    """
    files: list[tuple[str, str]] = []
    for section in re.split(r"(?m)^(?=diff --git )", diff):
        if not section.strip():
            continue
        match = _DIFF_FILE_HEADER_RE.match(section)
        files.append((match.group(2) if match else "(unknown)", section))
    return files


def _is_excluded_from_llm(path: str) -> bool:
    """Return True for data, generated, or bookkeeping files not worth LLM review."""
    return (
        path in _EXCLUDED_PATHS
        or path.endswith(_EXCLUDED_SUFFIXES)
        or path.startswith(_EXCLUDED_PREFIXES)
    )


def _review_priority(path: str) -> int:
    """Lower sorts first; code carrying ESOD rules outranks tests and docs."""
    for rank, prefix in enumerate(_PATH_PRIORITY):
        if path.startswith(prefix):
            return rank
    return len(_PATH_PRIORITY)


def _plan_review_chunks(
    diff: str,
    max_chars: int = _MAX_CHARS_PER_CHUNK,
    max_chunks: int = _MAX_LLM_CHUNKS,
) -> tuple[list[tuple[list[str], str]], list[str]]:
    """
    Pack the reviewable part of a diff into LLM-sized chunks.

    Files are packed whole. A single file larger than max_chars is truncated,
    and files beyond max_chunks are dropped; both are reported in the notes so the
    PR comment states exactly what the LLM did not see.

    Args:
        diff: Unified diff text for the whole PR.
        max_chars: Character budget per chunk.
        max_chunks: Maximum number of chunks (one LLM call each).

    Returns:
        (chunks, coverage_notes) where each chunk is (file paths, diff text).
    """
    notes: list[str] = []
    files = _split_diff_by_file(diff)

    excluded = [path for path, _ in files if _is_excluded_from_llm(path)]
    if excluded:
        notes.append(
            "Excluded from LLM review (data/generated/bookkeeping): " + ", ".join(excluded)
        )

    reviewable = sorted(
        ((path, sec) for path, sec in files if not _is_excluded_from_llm(path)),
        key=lambda item: _review_priority(item[0]),
    )

    chunks: list[tuple[list[str], str]] = []
    paths: list[str] = []
    parts: list[str] = []
    size = 0
    truncated: list[str] = []
    for path, section in reviewable:
        if len(section) > max_chars:
            section = section[:max_chars]
            truncated.append(path)
        if parts and size + len(section) > max_chars:
            chunks.append((paths, "".join(parts)))
            paths, parts, size = [], [], 0
        paths.append(path)
        parts.append(section)
        size += len(section)
    if parts:
        chunks.append((paths, "".join(parts)))

    if truncated:
        notes.append(
            f"Truncated to {max_chars} characters (remainder not reviewed): " + ", ".join(truncated)
        )
    if len(chunks) > max_chunks:
        dropped = [path for chunk_paths, _ in chunks[max_chunks:] for path in chunk_paths]
        notes.append(
            f"Not reviewed by LLM (over the {max_chunks}-chunk limit): " + ", ".join(dropped)
        )
        chunks = chunks[:max_chunks]
    return chunks, notes


def _extract_json_array(text: str) -> object | None:
    """Return the JSON value embedded in LLM text (fences tolerated), or None if invalid."""
    stripped = text.strip()
    fence = _JSON_FENCE_RE.match(stripped)
    if fence:
        stripped = fence.group(1)
    start, end = stripped.find("["), stripped.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        parsed: object = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed


def _unparsed_finding(message: str) -> ReviewFinding:
    """Build the visible SUGGESTION used when LLM output cannot be trusted as structured."""
    return ReviewFinding(
        location="(llm-review)",
        severity=ReviewSeverity.SUGGESTION,
        rule=f"{_LLM_RULE_PREFIX}unparsed",
        message=message[:_MAX_FINDING_MESSAGE_CHARS],
        suggestion=None,
    )


def _parse_llm_findings(
    llm_text: str,
    pr_number: int,
) -> list[ReviewFinding]:
    """
    Parse the LLM's JSON array into ReviewFinding objects.

    Severity is preserved, so LLM blockers count toward the status line. Output that
    is not valid JSON, or elements that fail validation, are never dropped silently:
    they surface as a visible `llm:unparsed` SUGGESTION.

    Args:
        llm_text: Raw text returned by LLMWrapper.complete().
        pr_number: PR number, used for logging context.

    Returns:
        List of ReviewFinding parsed from llm_text; every rule is prefixed "llm:".
    """
    if llm_text.strip().lower().startswith("no findings"):
        logger.info("PR #%d: LLM review returned no findings.", pr_number)
        return []

    parsed = _extract_json_array(llm_text)
    if not isinstance(parsed, list):
        logger.warning("PR #%d: LLM output was not a JSON array.", pr_number)
        excerpt = llm_text.strip()[:_MAX_UNPARSED_EXCERPT_CHARS]
        return [
            _unparsed_finding(f"LLM output was not valid structured findings. Excerpt: {excerpt}")
        ]

    findings: list[ReviewFinding] = []
    malformed = 0
    for item in parsed:
        candidate = item
        if isinstance(item, dict) and isinstance(item.get("severity"), str):
            candidate = {**item, "severity": item["severity"].strip().lower()}
        try:
            payload = _LLMFindingPayload.model_validate(candidate)
        except ValidationError as exc:
            logger.debug("PR #%d: malformed LLM item %r: %s", pr_number, item, exc)
            malformed += 1
            continue
        rule = payload.rule
        if not rule.startswith(_LLM_RULE_PREFIX):
            rule = f"{_LLM_RULE_PREFIX}{rule}"
        findings.append(
            ReviewFinding(
                location=payload.file_path,
                line_number=payload.line_number,
                severity=payload.severity,
                rule=rule,
                message=payload.message[:_MAX_FINDING_MESSAGE_CHARS],
                suggestion=payload.suggestion,
            )
        )
    if malformed:
        logger.warning("PR #%d: %d malformed LLM finding(s) dropped.", pr_number, malformed)
        findings.append(
            _unparsed_finding(f"{malformed} LLM finding(s) were malformed and could not be shown.")
        )
    return findings


def _describe_llm_failure(exc: Exception) -> str:
    """Summarize an LLM failure without leaking response bodies or credentials."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return type(exc).__name__ + (f" (HTTP {status})" if status else "")


def _run_llm_review(
    metadata: PRMetadata,
    model_id: str,
    chunks: list[tuple[list[str], str]],
) -> tuple[list[ReviewFinding], list[str], str | None]:
    """
    Run the LLM review over each chunk, tolerating provider failure.

    A failure (billing, network, misconfiguration) stops further calls, is logged
    with its traceback, and is reported back as a reason instead of raising, so the
    deterministic checks are never lost.

    Args:
        metadata: PR metadata (title and branches go into the prompt).
        model_id: LLM model identifier.
        chunks: Output of _plan_review_chunks().

    Returns:
        (llm_findings, coverage_notes, unavailable_reason); reason is None on success.
    """
    wrapper = LLMWrapper(model_id=model_id)
    findings: list[ReviewFinding] = []
    notes: list[str] = []
    total = len(chunks)
    for index, (paths, text) in enumerate(chunks, start=1):
        prompt = _REVIEW_PROMPT_TEMPLATE.format(
            title=metadata.title,
            head_branch=metadata.head_branch,
            base_branch=metadata.base_branch,
            chunk_info=f"Chunk {index} of {total}. Files: {', '.join(paths)}",
            diff=text,
        )
        try:
            response = wrapper.complete(prompt=prompt)
        except Exception as exc:
            logger.warning(
                "PR #%d: LLM review failed on chunk %d/%d.",
                metadata.pr_number,
                index,
                total,
                exc_info=True,
            )
            unreviewed = [path for chunk_paths, _ in chunks[index - 1 :] for path in chunk_paths]
            notes.append("Not reviewed by LLM (provider failure): " + ", ".join(unreviewed))
            return findings, notes, _describe_llm_failure(exc)
        chunk_findings = _parse_llm_findings(response.content, metadata.pr_number)
        findings.extend(chunk_findings)
        logger.info(
            "PR #%d: LLM chunk %d/%d added %d findings.",
            metadata.pr_number,
            index,
            total,
            len(chunk_findings),
        )
    return findings, notes, None


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
      2. Split the diff per file, drop data/generated files, and send the rest to
         LLMWrapper in bounded chunks; the LLM returns structured JSON findings.
      3. Aggregate findings, tally severities, and set approved = (blockers == 0).

    Args:
        metadata: Validated PRMetadata for the pull request under review.
        model_id: LLM model identifier to use for narrative review.
                  Defaults to the module-level _REVIEW_MODEL_ID constant.

    Returns:
        PRReviewResult with all findings sorted by severity (blockers first)
        and a boolean approved flag.

    Never raises on LLM failure: the reason is recorded in
    PRReviewResult.llm_unavailable_reason and static checks are still returned.
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

    # --- LLM-assisted narrative review (chunked, failure-tolerant) ---
    coverage_notes: list[str] = []
    llm_unavailable_reason: str | None = None
    if metadata.diff:
        chunks, coverage_notes = _plan_review_chunks(metadata.diff)
        if chunks:
            llm_findings, failure_notes, llm_unavailable_reason = _run_llm_review(
                metadata, model_id, chunks
            )
            findings.extend(llm_findings)
            coverage_notes.extend(failure_notes)
        else:
            logger.warning("PR #%d: no reviewable files for the LLM pass.", metadata.pr_number)
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
    static_blocker_count = sum(
        1
        for f in findings
        if f.severity == ReviewSeverity.BLOCKER and not f.rule.startswith(_LLM_RULE_PREFIX)
    )
    approved = blocker_count == 0

    summary_parts = [
        f"PR #{metadata.pr_number} '{metadata.title}' review complete.",
        f"Findings: {blocker_count} blocker(s), {warning_count} warning(s), "
        f"{suggestion_count} suggestion(s).",
    ]
    if not approved:
        summary_parts.append(
            f"{blocker_count} blocker(s) must be resolved before this PR can be merged."
        )
    elif llm_unavailable_reason:
        summary_parts.append(
            "No blockers from deterministic checks; LLM review was incomplete "
            "(human approval required)."
        )
    else:
        summary_parts.append(
            "No blockers found — PR is eligible for merge (human approval required)."
        )

    result = PRReviewResult(
        pr_number=metadata.pr_number,
        reviewed_at=datetime.now(tz=UTC),
        findings=findings,
        summary=" ".join(summary_parts),
        approved=approved,
        blocker_count=blocker_count,
        warning_count=warning_count,
        suggestion_count=suggestion_count,
        static_blocker_count=static_blocker_count,
        coverage_notes=coverage_notes,
        llm_unavailable_reason=llm_unavailable_reason,
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
