"""
Compatibility shims for cross-Python features.

Provides a single source-of-truth for `StrEnum` so modules do not each
implement their own fallback, which confuses static analyzers like mypy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # For static type checkers prefer the stdlib name when available
    from enum import StrEnum

else:
    try:
        from enum import StrEnum as _StrEnum
    except Exception:
        try:
            from typing_extensions import StrEnum as _StrEnum  # type: ignore
        except Exception:
            from enum import Enum as _Enum

            class _StrEnum(str, _Enum):
                """Compatibility fallback for Python < 3.11."""

            _StrEnum = _StrEnum

    StrEnum = _StrEnum  # runtime name exported for imports

__all__ = ["StrEnum"]
