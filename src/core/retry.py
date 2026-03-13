"""
Shared retry configuration for the Energy Options Opportunity Agent.

All external API calls use @with_retry() from this module (ESOD Section 6).
This is the single source of truth for tenacity retry policy. Changes to
retry behaviour (number of attempts, backoff strategy, sleep logging) are
made once here rather than at every call site.

Usage:
    from src.core.retry import with_retry

    @with_retry()
    def fetch_crude_prices() -> list[RawPriceRecord]:
        ...
"""

from __future__ import annotations

from collections.abc import Callable
import logging
import os
from typing import TypeVar

from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., object])


def with_retry() -> Callable[[_F], _F]:
    """
    Return a configured tenacity retry decorator.

    Reads retry policy from environment variables with production-safe defaults:
      - TENACITY_MAX_RETRIES: maximum number of attempts (default: 5)
      - TENACITY_WAIT_MULTIPLIER: exponential backoff base multiplier in seconds (default: 1)
      - TENACITY_WAIT_MAX: maximum wait between retries in seconds (default: 60)

    Logs the exception and retry attempt number at WARNING level before each
    sleep interval via tenacity's before_sleep_log hook.

    Returns:
        Configured tenacity retry decorator. Apply as ``@with_retry()``.

    Raises:
        RuntimeError: Re-raises the original exception after all attempts are
            exhausted (reraise=True).

    Example::

        @with_retry()
        def fetch_crude_prices() -> list[RawPriceRecord]:
            ...
    """
    return retry(
        stop=stop_after_attempt(int(os.environ.get("TENACITY_MAX_RETRIES", "5"))),
        wait=wait_exponential(
            multiplier=int(os.environ.get("TENACITY_WAIT_MULTIPLIER", "1")),
            max=int(os.environ.get("TENACITY_WAIT_MAX", "60")),
        ),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
