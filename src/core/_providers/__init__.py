"""
src/core/_providers/

Lazy-loaded provider backends for LLMWrapper (ESOD Section 5.3).

Each module in this package implements a single provider. They are imported
only when the matching LLM_PROVIDER environment variable value is selected —
never at module-load time in agent code.

Available providers:
    anthropic_http  — Anthropic Messages API via HTTP (requests library)
"""
