from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess


MODULE_PATH = Path(__file__).resolve().parents[2] / "channels" / "webhook" / "copilot_responder.py"
SPEC = importlib.util.spec_from_file_location("discord_copilot_responder", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MODULE.ResponderRequest.model_rebuild(
    _types_namespace={
        "ResponderAuthor": MODULE.ResponderAuthor,
        "ResponderAttachment": MODULE.ResponderAttachment,
    }
)


def _request(*, user_id: str = "u1", channel_id: str = "c1"):
    return MODULE.ResponderRequest(
        content="test",
        author=MODULE.ResponderAuthor(id=user_id, username="tester"),
        channelId=channel_id,
    )


def test_detect_tool_request_for_open_pr_phrase() -> None:
    tool = MODULE.detect_tool_request("Any open PRs?")

    assert tool is not None
    assert tool.action == "prs"


def test_detect_tool_request_for_explicit_read() -> None:
    tool = MODULE.detect_tool_request("tool read README.md")

    assert tool is not None
    assert tool.action == "read"
    assert tool.argument == "README.md"


def test_detect_tool_request_for_pr_number() -> None:
    tool = MODULE.detect_tool_request("tool pr 188")

    assert tool is not None
    assert tool.action == "pr_view"
    assert tool.argument == "188"


def test_detect_tool_request_for_workflow_help() -> None:
    tool = MODULE.detect_tool_request("tool workflow")

    assert tool is not None
    assert tool.action == "workflow_help"


def test_detect_tool_request_for_ci_and_digest_commands() -> None:
    ci_tool = MODULE.detect_tool_request("tool ci")
    digest_tool = MODULE.detect_tool_request("tool digest")
    ship_prep_tool = MODULE.detect_tool_request("tool ship prep")

    assert ci_tool is not None and ci_tool.action == "ci"
    assert digest_tool is not None and digest_tool.action == "digest"
    assert ship_prep_tool is not None and ship_prep_tool.action == "ship_prep"


def test_run_tool_request_unknown() -> None:
    response = MODULE.run_tool_request(MODULE.ToolRequest(action="unknown", argument="deploy now"), _request())

    assert "Unknown tool request" in response


def test_run_tool_request_help() -> None:
    response = MODULE.run_tool_request(MODULE.ToolRequest(action="help"), _request())

    assert "tool prs" in response
    assert "tool search <pattern>" in response


def test_run_tool_request_workflow_help() -> None:
    response = MODULE.run_tool_request(MODULE.ToolRequest(action="workflow_help"), _request())

    assert "tool pr <number>" in response
    assert "tool test <target>" in response


def test_read_repo_file_rejects_parent_escape() -> None:
    response = MODULE.run_tool_request(MODULE.ToolRequest(action="read", argument="..\\secrets.txt"), _request())

    assert "Path must stay within the repository root" in response


def test_format_prs_handles_empty_list() -> None:
    assert MODULE._format_prs("[]") == "No open PRs."


def test_run_tool_request_status_formats_git_output(monkeypatch) -> None:
    def fake_run(_args: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["git", "status"],
            returncode=0,
            stdout="## feature/test\n M src/file.py\n",
            stderr="",
        )

    monkeypatch.setattr(MODULE, "_run_command", fake_run)

    response = MODULE.run_tool_request(MODULE.ToolRequest(action="status"), _request())

    assert "feature/test" in response
    assert "src/file.py" in response


def test_run_tool_request_prs_formats_gh_output(monkeypatch) -> None:
    def fake_run(_args: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["gh", "pr", "list"],
            returncode=0,
            stdout=(
                '[{"number":182,"title":"Add tool bridge","headRefName":"feature/tool-bridge",'
                '"baseRefName":"develop","isDraft":false,"url":"https://example.test/pr/182"}]'
            ),
            stderr="",
        )

    monkeypatch.setattr(MODULE, "_run_command", fake_run)

    response = MODULE.run_tool_request(MODULE.ToolRequest(action="prs"), _request())

    assert "Open PRs:" in response
    assert "#182 Add tool bridge" in response
    assert "https://example.test/pr/182" in response


def test_run_tool_request_ci_formats_runs(monkeypatch) -> None:
    monkeypatch.setattr(
        MODULE,
        "_gh_run_list",
        lambda limit=8: (
            True,
            '[{"databaseId":1001,"workflowName":"CI","headBranch":"develop","status":"completed","conclusion":"success","url":"https://example.test/runs/1001"}]',
        ),
    )

    response = MODULE.run_tool_request(MODULE.ToolRequest(action="ci"), _request())

    assert "CI runs:" in response
    assert "#1001" in response


def test_run_tool_request_ci_failed_filters_failures(monkeypatch) -> None:
    monkeypatch.setattr(
        MODULE,
        "_gh_run_list",
        lambda limit=12: (
            True,
            (
                '[{"databaseId":1001,"workflowName":"CI","headBranch":"develop","status":"completed","conclusion":"success","url":"u1"},'
                '{"databaseId":1002,"workflowName":"CI","headBranch":"feature/x","status":"completed","conclusion":"failure","url":"u2"}]'
            ),
        ),
    )

    response = MODULE.run_tool_request(MODULE.ToolRequest(action="ci_failed"), _request())

    assert "#1002" in response
    assert "#1001" not in response


def test_run_command_timeout_returns_completed_process(monkeypatch) -> None:
    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["gh", "run", "list"], timeout=15)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = MODULE._run_command(["gh", "run", "list"], timeout=15)

    assert result.returncode == 124
    assert "Command timed out" in result.stderr


def test_run_tool_request_pr_view_formats_output(monkeypatch) -> None:
    def fake_run(_args: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["gh", "pr", "view", "188"],
            returncode=0,
            stdout=(
                '{"title":"Edge harness","state":"OPEN","isDraft":false,'
                '"headRefName":"feature/137","baseRefName":"develop",'
                '"url":"https://example.test/pr/188","author":{"login":"realoldtom"},'
                '"reviewDecision":"APPROVED","mergeStateStatus":"CLEAN","comments":{"totalCount":3}}'
            ),
            stderr="",
        )

    monkeypatch.setattr(MODULE, "_run_command", fake_run)

    response = MODULE.run_tool_request(MODULE.ToolRequest(action="pr_view", argument="188"), _request())

    assert "PR details:" in response
    assert "Edge harness" in response
    assert "realoldtom" in response
    assert "reviewDecision" in response


def test_run_tool_request_issue_view_formats_output(monkeypatch) -> None:
    def fake_run(_args: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["gh", "issue", "view", "170"],
            returncode=0,
            stdout=(
                '{"number":170,"title":"Vendor selection","state":"OPEN",'
                '"url":"https://example.test/issues/170",'
                '"assignees":[{"login":"realoldtom"}],"labels":[{"name":"in-progress"}],'
                '"comments":5,"body":"Vendor decision and criteria"}'
            ),
            stderr="",
        )

    monkeypatch.setattr(MODULE, "_run_command", fake_run)

    response = MODULE.run_tool_request(MODULE.ToolRequest(action="issue_view", argument="170"), _request())

    assert "Issue details:" in response
    assert "Vendor selection" in response
    assert "in-progress" in response
    assert "preview" in response


def test_run_tool_request_test_rejects_unsafe_target() -> None:
    response = MODULE.run_tool_request(MODULE.ToolRequest(action="test", argument="../../bad"), _request())

    assert "Unsafe test target" in response


def test_detect_tool_request_for_confirm_token() -> None:
    tool = MODULE.detect_tool_request("tool confirm deadbeef")

    assert tool is not None
    assert tool.action == "confirm"
    assert tool.argument == "deadbeef"


def test_write_help_includes_confirm_flow() -> None:
    response = MODULE.run_tool_request(MODULE.ToolRequest(action="write_help"), _request())

    assert "tool branch create" in response
    assert "tool confirm <token>" in response


def test_branch_create_generates_confirmation_token(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "_create_write_approval", lambda **_kwargs: "abc12345")
    monkeypatch.setattr(MODULE, "_is_write_allowed", lambda _request: (True, None))

    response = MODULE.run_tool_request(
        MODULE.ToolRequest(action="branch_create", argument="feature/test-branch"),
        _request(user_id="u123", channel_id="chan456"),
    )

    assert "tool confirm abc12345" in response


def test_confirm_rejects_wrong_user_or_channel(monkeypatch) -> None:
    record = {
        "action": "branch_create",
        "args": {"branch": "feature/test"},
        "authorId": "owner",
        "channelId": "chan-owner",
    }
    monkeypatch.setattr(MODULE, "_is_write_allowed", lambda _request: (True, None))
    monkeypatch.setattr(MODULE, "_consume_write_approval", lambda _token: record)

    response = MODULE.run_tool_request(
        MODULE.ToolRequest(action="confirm", argument="abc"),
        _request(user_id="other", channel_id="chan-owner"),
    )

    assert "does not match this user/channel" in response


def test_confirm_executes_approved_action(monkeypatch) -> None:
    record = {
        "action": "branch_create",
        "args": {"branch": "feature/test"},
        "authorId": "u1",
        "channelId": "c1",
    }
    monkeypatch.setattr(MODULE, "_is_write_allowed", lambda _request: (True, None))
    monkeypatch.setattr(MODULE, "_consume_write_approval", lambda _token: record)
    monkeypatch.setattr(MODULE, "_run_approved_write_action", lambda _record: "Branch created: feature/test")

    response = MODULE.run_tool_request(MODULE.ToolRequest(action="confirm", argument="abc"), _request())

    assert "Branch created" in response


def test_write_action_respects_policy_denial(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "_is_write_allowed", lambda _request: (False, "Write action denied"))

    response = MODULE.run_tool_request(
        MODULE.ToolRequest(action="branch_create", argument="feature/test-policy"),
        _request(),
    )

    assert "Write action denied" in response


def test_ship_prep_command_uses_collector(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "_collect_ship_prep_report", lambda: "Ship prep report:\nall good")

    response = MODULE.run_tool_request(MODULE.ToolRequest(action="ship_prep"), _request())

    assert "Ship prep report" in response