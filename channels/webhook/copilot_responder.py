#!/usr/bin/env python
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.llm_wrapper import LLMWrapper  # noqa: E402


DEFAULT_MODEL_ID = "claude-sonnet-4-6"
DEFAULT_SYSTEM_PROMPT = (
    "You are GitHub Copilot inside a Discord bridge. "
    "Answer directly, briefly, and helpfully. "
    "If the user asks for code, provide concise working code."
)
MAX_TOOL_OUTPUT_CHARS = 3500
MAX_READ_LINES = 120
MAX_SEARCH_MATCHES = 40
SAFE_PATH_PATTERN = re.compile(r"^[A-Za-z0-9_./\\:-]+$")
SAFE_BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")
WRITE_APPROVAL_TTL_SECONDS = 10 * 60
WRITE_APPROVALS_FILE = REPO_ROOT / "channels" / "webhook" / ".data" / "write_approvals.json"
POLICY_FILE = REPO_ROOT / "channels" / "webhook" / ".data" / "policy.json"


class ResponderAuthor(BaseModel):
    id: str | None = None
    username: str | None = None


class ResponderAttachment(BaseModel):
    url: str | None = None
    name: str | None = None


class ResponderRequest(BaseModel):
    requestId: str | None = None
    project: str = "default"
    content: str = ""
    author: ResponderAuthor | None = None
    channelId: str | None = None
    channelName: str | None = None
    attachments: list[ResponderAttachment] = Field(default_factory=list)


class ToolRequest(BaseModel):
    action: str
    argument: str = ""


def _parse_csv_env(var_name: str) -> set[str]:
    raw = (os.environ.get(var_name, "") or "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def build_prompt(request: ResponderRequest, system_prompt: str) -> str:
    author_name = (request.author.username if request.author else None) or "unknown"
    attachment_names = ", ".join(
        attachment.name or attachment.url or "attachment"
        for attachment in request.attachments
    ) or "none"

    return (
        f"{system_prompt}\n\n"
        f"Project: {request.project}\n"
        f"Author: {author_name}\n"
        f"Channel: {request.channelName or request.channelId or 'unknown'}\n"
        f"Attachments: {attachment_names}\n\n"
        "User message:\n"
        f"{request.content.strip() or '(empty message)'}\n"
    )


def detect_tool_request(content: str) -> ToolRequest | None:
    raw = content.strip()
    lowered = raw.lower()

    if not raw:
        return None

    if lowered in {"tool help", "tools", "tool", "help tools"}:
        return ToolRequest(action="help")

    if lowered.startswith("tool "):
        remainder = raw[5:].strip()
        lowered_remainder = remainder.lower()
        if not remainder:
            return ToolRequest(action="help")
        if lowered_remainder in {"prs", "pr", "open prs", "open pr", "pull requests", "pull request"}:
            return ToolRequest(action="prs")
        if lowered_remainder in {"workflow", "workflow help", "commands", "cmds"}:
            return ToolRequest(action="workflow_help")
        if lowered_remainder in {"ci", "checks", "actions"}:
            return ToolRequest(action="ci")
        if lowered_remainder in {"ci failed", "failed ci", "failing ci"}:
            return ToolRequest(action="ci_failed")
        if lowered_remainder in {"digest", "daily digest"}:
            return ToolRequest(action="digest")
        if lowered_remainder in {"ship prep", "ship-prep", "prep ship", "preflight"}:
            return ToolRequest(action="ship_prep")
        if lowered_remainder in {"status", "git status", "repo status"}:
            return ToolRequest(action="status")
        if lowered_remainder in {"write help", "writes", "write"}:
            return ToolRequest(action="write_help")
        if lowered_remainder in {"branch", "branches", "git branch", "current branch"}:
            return ToolRequest(action="branches")
        if lowered_remainder in {"log", "history", "git log"}:
            return ToolRequest(action="log")
        if lowered_remainder in {"diff", "git diff", "changes"}:
            return ToolRequest(action="diff")
        if lowered_remainder.startswith("pr "):
            return ToolRequest(action="pr_view", argument=remainder[3:].strip())
        if lowered_remainder.startswith("pr comment "):
            return ToolRequest(action="pr_comment", argument=remainder[11:].strip())
        if lowered_remainder.startswith("issue "):
            return ToolRequest(action="issue_view", argument=remainder[6:].strip())
        if lowered_remainder.startswith("issue label add "):
            return ToolRequest(action="issue_label_add", argument=remainder[16:].strip())
        if lowered_remainder.startswith("branch create "):
            return ToolRequest(action="branch_create", argument=remainder[14:].strip())
        if lowered_remainder.startswith("confirm "):
            return ToolRequest(action="confirm", argument=remainder[8:].strip())
        if lowered_remainder.startswith("test"):
            return ToolRequest(action="test", argument=remainder[4:].strip())
        if lowered_remainder.startswith("read "):
            return ToolRequest(action="read", argument=remainder[5:].strip())
        if lowered_remainder.startswith("search "):
            return ToolRequest(action="search", argument=remainder[7:].strip())
        return ToolRequest(action="unknown", argument=remainder)

    if re.search(r"\b(open|list|show|any)\b.*\b(pr|prs|pull request|pull requests)\b", lowered):
        return ToolRequest(action="prs")
    if lowered in {"status", "git status", "repo status"}:
        return ToolRequest(action="status")
    if re.fullmatch(r"(what('?s| is) )?(the )?(current )?branches?\??", lowered):
        return ToolRequest(action="branches")

    return None


def _truncate(text: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit - 15].rstrip()}\n...truncated"


def _run_command(args: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        command_text = " ".join(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=124,
            stdout="",
            stderr=f"Command timed out after {timeout}s: {command_text}",
        )


def _run_ripgrep(pattern: str) -> str:
    try:
        result = _run_command(
            [
                "rg",
                "-n",
                "--hidden",
                "--glob",
                "!.git",
                "--glob",
                "!node_modules",
                pattern,
                ".",
            ],
            timeout=20,
        )
    except FileNotFoundError:
        return "Search tool unavailable: `rg` is not installed in this environment."

    if result.returncode not in {0, 1}:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        return f"Search failed: {detail}"
    if result.returncode == 1 or not result.stdout.strip():
        return f"No matches for `{pattern}`."

    lines = result.stdout.strip().splitlines()[:MAX_SEARCH_MATCHES]
    return _truncate("Search results:\n" + "\n".join(lines))


def _resolve_repo_path(argument: str) -> Path:
    candidate = (REPO_ROOT / argument).resolve()
    try:
        candidate.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("Path must stay within the repository root") from exc
    if not candidate.exists():
        raise FileNotFoundError(f"File not found: {argument}")
    if not candidate.is_file():
        raise ValueError(f"Not a file: {argument}")
    return candidate


def _read_repo_file(argument: str) -> str:
    if not argument:
        return "Usage: `tool read <relative-path>`"

    try:
        candidate = _resolve_repo_path(argument)
    except (FileNotFoundError, ValueError) as exc:
        return str(exc)

    lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    visible = lines[:MAX_READ_LINES]
    body = "\n".join(visible)
    suffix = ""
    if len(lines) > MAX_READ_LINES:
        suffix = f"\n...truncated after {MAX_READ_LINES} lines"
    rel_path = candidate.relative_to(REPO_ROOT).as_posix()
    return _truncate(f"{rel_path}:\n{body}{suffix}")


def _format_prs(raw_json: str) -> str:
    items = json.loads(raw_json)
    if not items:
        return "No open PRs."

    lines = ["Open PRs:"]
    for item in items:
        number = item.get("number", "?")
        title = item.get("title", "(untitled)")
        branch = item.get("headRefName", "?")
        base = item.get("baseRefName", "?")
        draft = " [draft]" if item.get("isDraft") else ""
        url = item.get("url", "")
        lines.append(f"#{number}{draft} {title} ({branch} -> {base})")
        if url:
            lines.append(url)
    return _truncate("\n".join(lines))


def _parse_number(argument: str, label: str) -> int | None:
    if not argument or not argument.isdigit():
        return None
    value = int(argument)
    if value <= 0:
        return None
    return value


def _parse_number_and_text(argument: str) -> tuple[int, str] | None:
    parts = argument.strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        return None
    number = int(parts[0])
    if number <= 0:
        return None
    text = parts[1].strip()
    if not text:
        return None
    return number, text


def _load_policy() -> dict[str, object]:
    env_write_users = _parse_csv_env("DISCORD_WRITE_ALLOWED_USERS")
    env_write_projects = _parse_csv_env("DISCORD_WRITE_ALLOWED_PROJECTS")
    policy: dict[str, object] = {
        "writeAllowedUsers": sorted(env_write_users),
        "writeAllowedProjects": sorted(env_write_projects),
    }
    try:
        if POLICY_FILE.exists():
            parsed = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                for key in ("writeAllowedUsers", "writeAllowedProjects"):
                    value = parsed.get(key)
                    if isinstance(value, list):
                        policy[key] = [str(v).strip() for v in value if str(v).strip()]
    except (json.JSONDecodeError, OSError):
        pass

    return policy


def _is_write_allowed(request: ResponderRequest) -> tuple[bool, str | None]:
    policy = _load_policy()
    raw_users = policy.get("writeAllowedUsers")
    raw_projects = policy.get("writeAllowedProjects")
    allowed_users = set(raw_users) if isinstance(raw_users, list) else set()
    allowed_projects = set(raw_projects) if isinstance(raw_projects, list) else set()

    author_id = str((request.author.id if request.author else None) or "")
    project = str(request.project or "default")

    if allowed_users and author_id not in allowed_users:
        return False, "Write action denied: user is not in DISCORD_WRITE_ALLOWED_USERS policy."
    if allowed_projects and project not in allowed_projects:
        return False, f"Write action denied: project `{project}` is not in DISCORD_WRITE_ALLOWED_PROJECTS policy."

    return True, None


def _is_safe_path_argument(argument: str) -> bool:
    if not argument:
        return False
    if ".." in argument:
        return False
    return bool(SAFE_PATH_PATTERN.fullmatch(argument))


def _is_safe_branch_name(name: str) -> bool:
    if not name:
        return False
    if ".." in name:
        return False
    if name.startswith("/") or name.endswith("/"):
        return False
    if name.startswith("-"):
        return False
    return bool(SAFE_BRANCH_PATTERN.fullmatch(name))


def _gh_run_list(limit: int = 8) -> tuple[bool, str]:
    try:
        result = _run_command(
            [
                "gh",
                "run",
                "list",
                "--limit",
                str(limit),
                "--json",
                "databaseId,status,conclusion,name,workflowName,headBranch,url,createdAt",
            ]
        )
    except FileNotFoundError:
        return False, "GitHub CLI is not installed in this environment."

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        return False, f"CI query failed: {detail}"
    return True, result.stdout


def _format_ci_runs(raw_json: str, *, failed_only: bool = False) -> str:
    runs = json.loads(raw_json)
    if failed_only:
        runs = [
            r
            for r in runs
            if str(r.get("conclusion", "")).lower() in {"failure", "timed_out", "cancelled", "startup_failure"}
        ]
    if not runs:
        return "No matching CI runs found."

    lines = ["CI runs:"]
    for run in runs[:10]:
        run_id = run.get("databaseId", "?")
        wf = run.get("workflowName") or run.get("name") or "workflow"
        status = run.get("status", "?")
        conclusion = run.get("conclusion") or "(none)"
        branch = run.get("headBranch", "?")
        url = run.get("url", "")
        lines.append(f"- #{run_id} {wf} | branch={branch} | status={status} | conclusion={conclusion}")
        if url:
            lines.append(f"  {url}")
    return _truncate("\n".join(lines))


def _collect_ship_prep_report() -> str:
    status_res = _run_command(["git", "status", "--short", "--branch"])
    diff_res = _run_command(["git", "--no-pager", "diff", "--stat"])

    ci_ok, ci_payload = _gh_run_list(limit=6)

    sections = ["Ship prep report:"]
    if status_res.returncode == 0:
        sections.append("\n[git status]\n" + (status_res.stdout.strip() or "clean"))
    else:
        sections.append("\n[git status]\nfailed")

    if diff_res.returncode == 0:
        sections.append("\n[diff]\n" + (diff_res.stdout.strip() or "no unstaged diff"))
    else:
        sections.append("\n[diff]\nfailed")

    if ci_ok:
        sections.append("\n[ci]\n" + _format_ci_runs(ci_payload, failed_only=False))
    else:
        sections.append("\n[ci]\n" + ci_payload)

    return _truncate("\n".join(sections))


def _approvals_storage_load() -> dict[str, dict[str, object]]:
    try:
        raw = WRITE_APPROVALS_FILE.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}
    return {}


def _approvals_storage_save(data: dict[str, dict[str, object]]) -> None:
    WRITE_APPROVALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    WRITE_APPROVALS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _approvals_prune_expired(data: dict[str, dict[str, object]]) -> None:
    now = int(time.time())
    expired: list[str] = []
    for token, record in data.items():
        expires_raw = record.get("expiresAt", 0)
        try:
            expires_at = int(str(expires_raw))
        except (TypeError, ValueError):
            expires_at = 0
        if expires_at <= now:
            expired.append(token)
    for token in expired:
        data.pop(token, None)


def _create_write_approval(
    *,
    action: str,
    args: dict[str, object],
    author_id: str,
    channel_id: str,
) -> str:
    token = secrets.token_hex(4)
    data = _approvals_storage_load()
    _approvals_prune_expired(data)
    now = int(time.time())
    data[token] = {
        "action": action,
        "args": args,
        "authorId": author_id,
        "channelId": channel_id,
        "createdAt": now,
        "expiresAt": now + WRITE_APPROVAL_TTL_SECONDS,
    }
    _approvals_storage_save(data)
    return token


def _consume_write_approval(token: str) -> dict[str, object] | None:
    data = _approvals_storage_load()
    _approvals_prune_expired(data)
    record = data.pop(token, None)
    _approvals_storage_save(data)
    if not isinstance(record, dict):
        return None
    return record


def _run_approved_write_action(record: dict[str, object]) -> str:
    action = str(record.get("action", ""))
    args = record.get("args", {})
    if not isinstance(args, dict):
        return "Invalid approval payload."

    if action == "branch_create":
        branch = str(args.get("branch", "")).strip()
        result = _run_command(["git", "checkout", "-b", branch], timeout=30)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            return f"Branch create failed: {detail}"
        return _truncate(f"Branch created: {branch}\n{result.stdout}")

    if action == "pr_comment":
        number = int(args.get("number", 0))
        comment = str(args.get("comment", ""))
        result = _run_command(["gh", "pr", "comment", str(number), "--body", comment], timeout=45)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            return f"PR comment failed: {detail}"
        return "PR comment posted successfully."

    if action == "issue_label_add":
        number = int(args.get("number", 0))
        labels = str(args.get("labels", ""))
        result = _run_command(["gh", "issue", "edit", str(number), "--add-label", labels], timeout=45)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            return f"Issue label update failed: {detail}"
        return f"Issue #{number} updated with labels: {labels}"

    return f"Unsupported approved action: {action}"


def _format_single_pr(raw_json: str) -> str:
    item = json.loads(raw_json)
    author = (item.get("author") or {}).get("login", "unknown")
    draft = "yes" if item.get("isDraft") else "no"
    review_decision = item.get("reviewDecision") or "unknown"
    merge_state = item.get("mergeStateStatus") or "unknown"
    comments = item.get("comments", {}).get("totalCount", 0)
    return _truncate(
        "PR details:\n"
        f"- title: {item.get('title', '(untitled)')}\n"
        f"- state: {item.get('state', '?')}\n"
        f"- draft: {draft}\n"
        f"- reviewDecision: {review_decision}\n"
        f"- mergeState: {merge_state}\n"
        f"- comments: {comments}\n"
        f"- branch: {item.get('headRefName', '?')} -> {item.get('baseRefName', '?')}\n"
        f"- author: {author}\n"
        f"- url: {item.get('url', '')}"
    )


def _format_single_issue(raw_json: str) -> str:
    item = json.loads(raw_json)
    labels = [label.get("name", "") for label in item.get("labels", []) if label.get("name")]
    assignees = [assignee.get("login", "") for assignee in item.get("assignees", []) if assignee.get("login")]
    comments = item.get("comments", 0)
    body = (item.get("body") or "").strip()
    body_preview = body[:180] + ("..." if len(body) > 180 else "")
    return _truncate(
        "Issue details:\n"
        f"- number: {item.get('number', '?')}\n"
        f"- title: {item.get('title', '(untitled)')}\n"
        f"- state: {item.get('state', '?')}\n"
        f"- assignees: {', '.join(assignees) if assignees else 'none'}\n"
        f"- labels: {', '.join(labels) if labels else 'none'}\n"
        f"- comments: {comments}\n"
        f"- preview: {body_preview or '(no body)'}\n"
        f"- url: {item.get('url', '')}"
    )


def run_tool_request(tool: ToolRequest, request: ResponderRequest) -> str:
    if tool.action == "help":
        return (
            "Available Discord repo tools:\n"
            "- `tool prs` -> list open pull requests\n"
            "- `tool workflow` -> list curated workflow commands\n"
            "- `tool write help` -> list guarded write commands\n"
            "- `tool ci` -> recent GitHub Actions runs\n"
            "- `tool digest` -> repo and CI summary\n"
            "- `tool status` -> show git status\n"
            "- `tool branches` -> show current and local branches\n"
            "- `tool read <path>` -> read a repo file\n"
            "- `tool search <pattern>` -> search repo text"
        )

    if tool.action == "workflow_help":
        return (
            "Curated workflow commands:\n"
            "- `tool pr <number>` -> show PR details\n"
            "- `tool issue <number>` -> show issue details\n"
            "- `tool log` -> recent commit history\n"
            "- `tool diff` -> working tree diff summary\n"
            "- `tool ci` -> show recent workflow runs\n"
            "- `tool ci failed` -> show failing workflow runs\n"
            "- `tool ship prep` -> pre-ship report (status, diff, CI)\n"
            "- `tool digest` -> compact daily summary\n"
            "- `tool test <target>` -> run pytest on a specific target\n"
            "Example: `tool test tests/core/test_discord_copilot_responder.py`"
        )

    if tool.action == "write_help":
        return (
            "Guarded write commands (require confirmation token):\n"
            "- `tool branch create <name>`\n"
            "- `tool pr comment <number> <text>`\n"
            "- `tool issue label add <number> <label1,label2>`\n"
            "After requesting, run `tool confirm <token>` from the same channel."
        )

    if tool.action == "prs":
        try:
            result = _run_command(
                [
                    "gh",
                    "pr",
                    "list",
                    "--state",
                    "open",
                    "--limit",
                    "10",
                    "--json",
                    "number,title,headRefName,baseRefName,isDraft,url",
                ]
            )
        except FileNotFoundError:
            return "GitHub CLI is not installed in this environment."

        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            return f"PR query failed: {detail}"
        return _format_prs(result.stdout)

    if tool.action == "ci":
        ok, payload = _gh_run_list(limit=8)
        if not ok:
            return payload
        return _format_ci_runs(payload, failed_only=False)

    if tool.action == "ci_failed":
        ok, payload = _gh_run_list(limit=12)
        if not ok:
            return payload
        return _format_ci_runs(payload, failed_only=True)

    if tool.action == "digest":
        parts: list[str] = ["Digest:"]

        pr_ok = True
        pr_payload = ""
        try:
            pr_result = _run_command(
                [
                    "gh",
                    "pr",
                    "list",
                    "--state",
                    "open",
                    "--limit",
                    "20",
                    "--json",
                    "number,title,url",
                ]
            )
            if pr_result.returncode != 0:
                pr_ok = False
            else:
                pr_payload = pr_result.stdout
        except FileNotFoundError:
            pr_ok = False

        if pr_ok:
            try:
                pr_items = json.loads(pr_payload)
                parts.append(f"- open PRs: {len(pr_items)}")
                for item in pr_items[:3]:
                    parts.append(f"  - #{item.get('number', '?')} {item.get('title', '(untitled)')}")
            except json.JSONDecodeError:
                parts.append("- open PRs: unavailable")
        else:
            parts.append("- open PRs: unavailable")

        ci_ok, ci_payload = _gh_run_list(limit=10)
        if ci_ok:
            try:
                ci_items = json.loads(ci_payload)
                failed = [
                    r
                    for r in ci_items
                    if str(r.get("conclusion", "")).lower() in {"failure", "timed_out", "cancelled", "startup_failure"}
                ]
                parts.append(f"- failing CI runs: {len(failed)}")
            except json.JSONDecodeError:
                parts.append("- failing CI runs: unavailable")
        else:
            parts.append("- failing CI runs: unavailable")

        status_res = _run_command(["git", "status", "--short"])
        if status_res.returncode == 0:
            changed = [line for line in status_res.stdout.splitlines() if line.strip()]
            parts.append(f"- changed files: {len(changed)}")
        else:
            parts.append("- changed files: unavailable")

        return _truncate("\n".join(parts))

    if tool.action == "ship_prep":
        return _collect_ship_prep_report()

    if tool.action == "status":
        try:
            result = _run_command(["git", "status", "--short", "--branch"])
        except FileNotFoundError:
            return "Git is not installed in this environment."

        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            return f"git status failed: {detail}"
        return _truncate(result.stdout or "Repository is clean.")

    if tool.action == "branches":
        try:
            current = _run_command(["git", "branch", "--show-current"])
            branches = _run_command(["git", "branch", "--format", "%(refname:short)"])
        except FileNotFoundError:
            return "Git is not installed in this environment."

        if current.returncode != 0 or branches.returncode != 0:
            detail = current.stderr.strip() or branches.stderr.strip() or "git branch failed"
            return f"Branch query failed: {detail}"
        branch_lines = branches.stdout.strip().splitlines()
        current_branch = current.stdout.strip() or "(detached)"
        rendered = [f"Current branch: {current_branch}", "Local branches:"]
        rendered.extend(branch_lines[:25])
        return _truncate("\n".join(rendered))

    if tool.action == "log":
        try:
            result = _run_command(["git", "--no-pager", "log", "--oneline", "-10"])
        except FileNotFoundError:
            return "Git is not installed in this environment."

        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            return f"git log failed: {detail}"
        return _truncate("Recent commits:\n" + (result.stdout or "(none)"))

    if tool.action == "diff":
        try:
            result = _run_command(["git", "--no-pager", "diff", "--stat"])
        except FileNotFoundError:
            return "Git is not installed in this environment."

        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            return f"git diff failed: {detail}"
        if not result.stdout.strip():
            return "No unstaged diff changes."
        return _truncate("Diff summary:\n" + result.stdout)

    if tool.action == "pr_view":
        number = _parse_number(tool.argument, "pr")
        if number is None:
            return "Usage: `tool pr <number>`"
        try:
            result = _run_command(
                [
                    "gh",
                    "pr",
                    "view",
                    str(number),
                    "--json",
                    "title,state,isDraft,headRefName,baseRefName,url,author,reviewDecision,mergeStateStatus,comments",
                ]
            )
        except FileNotFoundError:
            return "GitHub CLI is not installed in this environment."
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            return f"PR view failed: {detail}"
        return _format_single_pr(result.stdout)

    if tool.action == "branch_create":
        allowed, reason = _is_write_allowed(request)
        if not allowed:
            return str(reason)
        branch = tool.argument.strip()
        if not _is_safe_branch_name(branch):
            return "Usage: `tool branch create <safe-branch-name>`"
        author_id = (request.author.id if request.author else None) or "unknown"
        channel_id = request.channelId or "unknown"
        token = _create_write_approval(
            action="branch_create",
            args={"branch": branch},
            author_id=str(author_id),
            channel_id=str(channel_id),
        )
        return (
            f"Ready to create branch `{branch}`. "
            f"Confirm with `tool confirm {token}` within {WRITE_APPROVAL_TTL_SECONDS // 60} minutes."
        )

    if tool.action == "pr_comment":
        allowed, reason = _is_write_allowed(request)
        if not allowed:
            return str(reason)
        parsed = _parse_number_and_text(tool.argument)
        if parsed is None:
            return "Usage: `tool pr comment <number> <text>`"
        number, comment = parsed
        author_id = (request.author.id if request.author else None) or "unknown"
        channel_id = request.channelId or "unknown"
        token = _create_write_approval(
            action="pr_comment",
            args={"number": number, "comment": comment},
            author_id=str(author_id),
            channel_id=str(channel_id),
        )
        return (
            f"Ready to post comment to PR #{number}. "
            f"Confirm with `tool confirm {token}` within {WRITE_APPROVAL_TTL_SECONDS // 60} minutes."
        )

    if tool.action == "issue_view":
        number = _parse_number(tool.argument, "issue")
        if number is None:
            return "Usage: `tool issue <number>`"
        try:
            result = _run_command(
                [
                    "gh",
                    "issue",
                    "view",
                    str(number),
                    "--json",
                    "number,title,state,url,assignees,labels,comments,body",
                ]
            )
        except FileNotFoundError:
            return "GitHub CLI is not installed in this environment."
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            return f"Issue view failed: {detail}"
        return _format_single_issue(result.stdout)

    if tool.action == "issue_label_add":
        allowed, reason = _is_write_allowed(request)
        if not allowed:
            return str(reason)
        parsed = _parse_number_and_text(tool.argument)
        if parsed is None:
            return "Usage: `tool issue label add <number> <label1,label2>`"
        number, labels = parsed
        safe_labels = labels.replace(" ", "")
        if not safe_labels:
            return "Usage: `tool issue label add <number> <label1,label2>`"
        author_id = (request.author.id if request.author else None) or "unknown"
        channel_id = request.channelId or "unknown"
        token = _create_write_approval(
            action="issue_label_add",
            args={"number": number, "labels": safe_labels},
            author_id=str(author_id),
            channel_id=str(channel_id),
        )
        return (
            f"Ready to add labels `{safe_labels}` to issue #{number}. "
            f"Confirm with `tool confirm {token}` within {WRITE_APPROVAL_TTL_SECONDS // 60} minutes."
        )

    if tool.action == "confirm":
        allowed, reason = _is_write_allowed(request)
        if not allowed:
            return str(reason)
        token = tool.argument.strip()
        if not token:
            return "Usage: `tool confirm <token>`"
        record = _consume_write_approval(token)
        if not record:
            return "Confirmation token not found or expired."
        expected_author = str(record.get("authorId", ""))
        expected_channel = str(record.get("channelId", ""))
        actual_author = str((request.author.id if request.author else None) or "unknown")
        actual_channel = str(request.channelId or "unknown")
        if expected_author != actual_author or expected_channel != actual_channel:
            return "Confirmation token does not match this user/channel."
        return _run_approved_write_action(record)

    if tool.action == "test":
        target = tool.argument.strip()
        if not target:
            return "Usage: `tool test <pytest-target>`"
        if not _is_safe_path_argument(target):
            return "Unsafe test target. Use a simple repo-relative path such as tests/core/test_discord_copilot_responder.py"
        try:
            result = _run_command([sys.executable, "-m", "pytest", target, "-q"], timeout=180)
        except FileNotFoundError:
            return "Python is not installed in this environment."

        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        status = "passed" if result.returncode == 0 else f"failed (exit {result.returncode})"
        return _truncate(f"Pytest {status}:\n{output}")

    if tool.action == "read":
        return _read_repo_file(tool.argument)

    if tool.action == "search":
        if not tool.argument:
            return "Usage: `tool search <pattern>`"
        return _run_ripgrep(tool.argument)

    if tool.action == "unknown":
        return f"Unknown tool request: `{tool.argument}`. Try `tool help`."

    return f"Unsupported tool action: {tool.action}"


def main() -> int:
    raw = sys.stdin.read().strip() or "{}"
    payload = json.loads(raw)
    request = ResponderRequest.model_validate(payload)

    tool_request = detect_tool_request(request.content)
    if tool_request is not None:
        sys.stdout.write(json.dumps({"ok": True, "response": run_tool_request(tool_request, request)}))
        return 0

    model_id = payload.get("model_id") or DEFAULT_MODEL_ID
    system_prompt = payload.get("system_prompt") or DEFAULT_SYSTEM_PROMPT

    wrapper = LLMWrapper(model_id=model_id)
    response = wrapper.complete(prompt=build_prompt(request, system_prompt))

    sys.stdout.write(json.dumps({"ok": True, "response": response.content}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}))
        raise SystemExit(1)