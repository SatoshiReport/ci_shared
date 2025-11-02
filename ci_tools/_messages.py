"""Shared helpers for formatting exception messages."""

from __future__ import annotations

from typing import Optional


def format_default_message(default_message: str, detail: Optional[str]) -> str:
    """Return the formatted message used by our exception helpers."""
    if detail is None:
        return default_message
    return f"{default_message}: {detail}"


__all__ = ["format_default_message"]
