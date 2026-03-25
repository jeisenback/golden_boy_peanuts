#!/usr/bin/env python
from __future__ import annotations

import json
import sys
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


def main() -> int:
    raw = sys.stdin.read().strip() or "{}"
    payload = json.loads(raw)
    request = ResponderRequest.model_validate(payload)

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