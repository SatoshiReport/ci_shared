"""Shared JSON configuration loading helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def load_json_config(
    repo_root: Path,
    candidates: tuple[str, ...],
    *,
    warn_on_error: bool = True,
    missing_value: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load JSON configuration from the first available candidate file."""
    if missing_value is None:
        missing_value = {}

    for candidate_name in candidates:
        candidate_path = repo_root / candidate_name
        if not candidate_path.is_file():
            continue
        try:
            with candidate_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError:
            if warn_on_error:
                print(
                    f"[warning] Failed to parse {candidate_path}; using defaults.",
                    file=sys.stderr,
                )
            continue
        if isinstance(data, dict):
            return data
    return missing_value
