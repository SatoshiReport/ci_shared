"""Configuration helpers and constants for the CI runtime."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

CONFIG_CANDIDATES = ("ci_shared.config.json", ".ci_shared.config.json")
DEFAULT_PROTECTED_PATH_PREFIXES: tuple[str, ...] = (
    "ci.py",
    "ci_tools/",
    "scripts/ci.sh",
    "Makefile",
)
RISKY_PATTERNS = (
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r"rm\s+-rf"),
    re.compile(r"subprocess\.run\([^)]*['\"]rm['\"]"),
)
REQUIRED_MODEL = "gpt-5-codex"
REASONING_EFFORT_CHOICES: tuple[str, ...] = ("low", "medium", "high")
DEFAULT_REASONING_EFFORT = "high"


def detect_repo_root() -> Path:
    """Best-effort detection of the repository root."""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        candidate = Path(result.stdout.strip())
        if candidate.exists():
            return candidate
    except (subprocess.CalledProcessError, FileNotFoundError):  # pragma: no cover
        pass
    return Path.cwd()


def load_repo_config(repo_root: Path) -> dict[str, Any]:
    """Load shared CI configuration when available."""

    for relative in CONFIG_CANDIDATES:
        candidate = repo_root / relative
        if not candidate.is_file():
            continue
        try:
            with candidate.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError:
            print(
                f"[warning] Failed to parse {candidate}; using defaults.",
                file=sys.stderr,
            )
            continue
        if isinstance(data, dict):
            return data
    return {}


def _coerce_repo_context(config: dict[str, Any], initial: str) -> str:
    raw = config.get("repo_context")
    if isinstance(raw, str):
        return raw
    return initial


def _coerce_protected_prefixes(
    config: dict[str, Any],
    initial: Iterable[str],
) -> tuple[str, ...]:
    raw = config.get("protected_path_prefixes")
    if isinstance(raw, (list, tuple, set)):
        return tuple(str(item) for item in raw)
    return tuple(initial)


def _coerce_coverage_threshold(config: dict[str, Any], initial: float) -> float:
    raw = config.get("coverage_threshold")
    if isinstance(raw, (int, float, str)):
        try:
            return float(raw)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return initial
    return initial


REPO_ROOT = detect_repo_root()
REPO_CONFIG = load_repo_config(REPO_ROOT)
DEFAULT_REPO_CONTEXT = (
    "You are assisting with continuous integration fixes for this repository.\n"
    "Repository facts:\n"
    "- Python 3.10+ project using PEP 8 conventions and four-space indentation.\n"
    "- Source lives under src/, tests mirror that structure under tests/.\n"
    "- Avoid committing secrets, install dependencies via scripts/requirements.txt when needed,\n"
    "  and prefer focused edits rather than sweeping rewrites.\n"
    "When CI fails, respond with a unified diff (a/ b/ prefixes) that can be applied with\n"
    "`patch -p1`. Keep the patch minimal, and mention any follow-up steps if the fix\n"
    "requires manual verification."
)
REPO_CONTEXT = _coerce_repo_context(REPO_CONFIG, DEFAULT_REPO_CONTEXT)
PROTECTED_PATH_PREFIXES = _coerce_protected_prefixes(
    REPO_CONFIG, DEFAULT_PROTECTED_PATH_PREFIXES
)
COVERAGE_THRESHOLD = _coerce_coverage_threshold(REPO_CONFIG, 80.0)


__all__ = [
    "CONFIG_CANDIDATES",
    "DEFAULT_PROTECTED_PATH_PREFIXES",
    "RISKY_PATTERNS",
    "REQUIRED_MODEL",
    "REASONING_EFFORT_CHOICES",
    "DEFAULT_REASONING_EFFORT",
    "detect_repo_root",
    "load_repo_config",
    "REPO_ROOT",
    "REPO_CONFIG",
    "REPO_CONTEXT",
    "PROTECTED_PATH_PREFIXES",
    "COVERAGE_THRESHOLD",
]
