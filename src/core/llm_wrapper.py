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

import logging
import os
from dataclasses import dataclass, field
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
    isolated in src/core/_providers/ (future issue).
    """

    def __init__(self, model_id: str) -> None:
        """
        Initialize the wrapper with a specific model identifier.

        Args:
            model_id: The model to use, e.g. "claude-sonnet-4-5" or "gpt-4o".
        """
        self.model_id = model_id
        self.provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()

    def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
        """
        Send a prompt to the configured LLM provider and return a normalized response.

        Args:
            prompt: The text prompt to send to the model.
            **kwargs: Additional provider-specific parameters (e.g., max_tokens).

        Returns:
            LLMResponse with normalized content, model_id, and provider fields.

        Raises:
            NotImplementedError: Until provider backends are implemented.
        """
        raise NotImplementedError(
            "LLMWrapper.complete() is not yet implemented. "
            "TODO: Implement provider backends in src/core/_providers/. "
            "See ESOD Section 5.3 for interface contract."
        )
