"""
llm_wrapper.py

Provider-agnostic LLM interface (ESOD Section 5.3).

ESOD rule: all LLM calls go through this wrapper. No direct provider SDK
imports in agent code. No langchain.* or langgraph.* imports anywhere in src/.

Usage:
    from src.core.llm_wrapper import LLMWrapper, LLMResponse
    wrapper = LLMWrapper(model_id="claude-sonnet-4-5")
    response = wrapper.complete(prompt="Summarize this market data...")
    print(response.content)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """
    Normalized response returned by LLMWrapper.complete().

    Attributes:
        content: Text output from the model.
        model_id: Model identifier used for this call.
        provider: Provider name (e.g., "anthropic", "openai").
        raw: Raw provider response object. Do not depend on this in production code.
    """

    content: str
    model_id: str
    provider: str
    raw: Any = field(default=None, repr=False)


class LLMProviderError(Exception):
    """Raised when the LLM provider is misconfigured or unavailable."""


class LLMWrapper:
    """
    Provider-agnostic wrapper around LLM API calls.

    Reads LLM_PROVIDER from the environment to select the backend.
    No provider SDK is imported at module level — imports are lazy and
    isolated in src/core/_providers/.

    Supported providers:
        anthropic  — Anthropic Messages API via HTTP (requests library)
    """

    def __init__(self, model_id: str) -> None:
        """
        Initialize the wrapper with a specific model identifier.

        Args:
            model_id: The model to use, e.g. "claude-sonnet-4-5" or "gpt-4o".
        """
        self.model_id = model_id
        self.provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()

    def complete(self, prompt: str, **kwargs: object) -> LLMResponse:
        """
        Send a prompt to the configured LLM provider and return a normalized response.

        Dispatches to the backend selected by the LLM_PROVIDER environment variable.
        Provider modules are imported lazily so unused providers have zero import cost.

        Args:
            prompt: The text prompt to send to the model.
            **kwargs: Additional provider-specific parameters (e.g., max_tokens).

        Returns:
            LLMResponse with normalized content, model_id, and provider fields.

        Raises:
            LLMProviderError: If LLM_PROVIDER is set to an unsupported value.
            EnvironmentError: If required provider credentials are missing.
        """
        if self.provider == "anthropic":
            from src.core._providers import anthropic_http  # lazy import

            raw = anthropic_http.complete(
                model_id=self.model_id,
                prompt=prompt,
                **{k: v for k, v in kwargs.items()},
            )
            content = anthropic_http.extract_text(raw)
            return LLMResponse(
                content=content,
                model_id=self.model_id,
                provider=self.provider,
                raw=raw,
            )

        raise LLMProviderError(
            f"Unsupported LLM_PROVIDER={self.provider!r}. "
            "Currently supported: 'anthropic'. "
            "Set LLM_PROVIDER=anthropic and ANTHROPIC_API_KEY in your environment."
        )
