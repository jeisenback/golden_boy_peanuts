"""
Anthropic Messages API provider for LLMWrapper.

Uses the `requests` library (already in requirements.txt) to POST directly
to the Anthropic Messages API endpoint. No anthropic SDK dependency.

Environment variables:
    ANTHROPIC_API_KEY   — required; Anthropic secret key
    ANTHROPIC_API_URL   — optional; defaults to https://api.anthropic.com/v1/messages
    ANTHROPIC_API_VERSION — optional; defaults to 2023-06-01

ESOD constraints: no langchain.*/langgraph.* imports, tenacity on all
external API calls, Pydantic validation at boundary.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_DEFAULT_API_URL = "https://api.anthropic.com/v1/messages"
_DEFAULT_API_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 4096


def _get_api_key() -> str:
    """
    Read the Anthropic API key from the environment.

    Returns:
        API key string.

    Raises:
        EnvironmentError: If ANTHROPIC_API_KEY is not set.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise OSError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Set it before using the Anthropic provider."
        )
    return key


@retry(
    stop=stop_after_attempt(int(os.environ.get("TENACITY_MAX_RETRIES", "5"))),
    wait=wait_exponential(
        multiplier=int(os.environ.get("TENACITY_WAIT_MULTIPLIER", "1")),
        max=int(os.environ.get("TENACITY_WAIT_MAX", "60")),
    ),
    reraise=True,
)
def complete(
    model_id: str,
    prompt: str,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    **kwargs: Any,  # noqa: ANN401
) -> dict[str, Any]:
    """
    Send a prompt to the Anthropic Messages API and return the raw response dict.

    Retries with exponential backoff on network errors and 5xx responses
    (ESOD Section 6 — tenacity on all external API calls).

    Args:
        model_id: Anthropic model identifier, e.g. "claude-sonnet-4-6".
        prompt: User-turn prompt text.
        max_tokens: Maximum tokens in the response. Defaults to 4096.
        **kwargs: Additional fields merged into the request body.

    Returns:
        Parsed JSON response dict from the Anthropic API.

    Raises:
        EnvironmentError: If ANTHROPIC_API_KEY is not set.
        requests.HTTPError: On non-2xx responses after all retries exhausted.
    """
    api_key = _get_api_key()
    api_url = os.environ.get("ANTHROPIC_API_URL", _DEFAULT_API_URL)
    api_version = os.environ.get("ANTHROPIC_API_VERSION", _DEFAULT_API_VERSION)

    headers = {
        "x-api-key": api_key,
        "anthropic-version": api_version,
        "content-type": "application/json",
    }

    body: dict[str, Any] = {
        "model": model_id,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        **kwargs,
    }

    logger.debug("Anthropic API request: model=%s max_tokens=%d", model_id, max_tokens)

    response = requests.post(api_url, headers=headers, json=body, timeout=120)

    if response.status_code >= 500:
        # Trigger tenacity retry on server errors (5xx)
        response.raise_for_status()

    # For 4xx errors (client errors), fail immediately without retrying
    # This avoids wasting retry attempts on misconfiguration, auth failures, etc.
    if not response.ok and response.status_code < 500:
        logger.error("Anthropic API error %d: %s", response.status_code, response.text[:500])
        response.raise_for_status()

    if not response.ok:
        response.raise_for_status()

    data: dict[str, Any] = response.json()
    logger.debug(
        "Anthropic API response: stop_reason=%s usage=%s",
        data.get("stop_reason"),
        data.get("usage"),
    )
    return data


def extract_text(response: dict[str, Any]) -> str:
    """
    Extract the assistant's text content from an Anthropic API response dict.

    Args:
        response: Parsed JSON response from the Anthropic Messages API.

    Returns:
        Concatenated text content from all text blocks in the response.

    Raises:
        ValueError: If the response contains no text content blocks.
    """
    content_blocks: list[dict[str, Any]] = response.get("content", [])
    texts = [block["text"] for block in content_blocks if block.get("type") == "text"]
    if not texts:
        raise ValueError(
            f"No text content blocks found in Anthropic response. "
            f"stop_reason={response.get('stop_reason')!r}"
        )
    return "\n".join(texts)
