"""Shared test fixtures and utilities for guard tests."""

from __future__ import annotations

import textwrap
from pathlib import Path


def write_module(path: Path, content: str) -> None:
    """Helper to write Python module content.

    Args:
        path: Path to write the module to (parent directory will be created)
        content: Module source code (will be dedented and stripped)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
