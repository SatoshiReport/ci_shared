"""File-based policy collectors (token scanning, legacy config detection)."""

from __future__ import annotations

import io
import tokenize
from typing import Dict, List, Set, Tuple

from .policy_context import (
    BANNED_KEYWORDS,
    CONFIG_EXTENSIONS,
    FLAGGED_TOKENS,
    LEGACY_CONFIG_TOKENS,
    LEGACY_SUFFIXES,
    ROOT,
    SUPPRESSION_PATTERNS,
    iter_module_contexts,
    normalize_path,
)


def _keyword_token_lines(
    source: str,
    keyword_lookup: Dict[str, str],
) -> Dict[str, Set[int]]:
    hits: Dict[str, Set[int]] = {}
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    except tokenize.TokenError:
        return {}
    for token in tokens:
        if token.type != tokenize.NAME:
            continue
        keyword = keyword_lookup.get(token.string.lower())
        if keyword:
            hits.setdefault(keyword, set()).add(token.start[0])
    return hits


def scan_keywords() -> Dict[str, Dict[str, List[int]]]:
    found: Dict[str, Dict[str, List[int]]] = {kw: {} for kw in BANNED_KEYWORDS}
    keyword_lookup = {kw.lower(): kw for kw in BANNED_KEYWORDS}

    for ctx in iter_module_contexts(include_source=True):
        if ctx.rel_path.startswith(("scripts/", "ci_runtime/", "vendor/")):
            continue
        source = ctx.source or ""
        keyword_hits = _keyword_token_lines(source, keyword_lookup)
        for keyword, lines in keyword_hits.items():
            if lines:
                found.setdefault(keyword, {})[ctx.rel_path] = sorted(lines)
    return found


def collect_flagged_tokens() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []
    for ctx in iter_module_contexts(include_source=True):
        if ctx.source is None:
            continue
        if ctx.rel_path.startswith(("scripts/", "ci_runtime/", "vendor/")):
            continue
        for lineno, line in enumerate(ctx.source.splitlines(), start=1):
            for token in FLAGGED_TOKENS:
                if token in line:
                    records.append((ctx.rel_path, lineno, token))
    return records


def collect_suppressions() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []
    for ctx in iter_module_contexts(include_source=True):
        if ctx.source is None:
            continue
        if ctx.rel_path.startswith(("scripts/", "ci_runtime/", "vendor/")):
            continue
        for lineno, line in enumerate(ctx.source.splitlines(), start=1):
            for token in SUPPRESSION_PATTERNS:
                if token in line:
                    records.append((ctx.rel_path, lineno, token))
    return records


def _build_legacy_patterns() -> (
    Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]]
):
    """Build forbidden patterns for legacy module detection."""
    forbidden_suffixes = tuple(f"{suffix}.py" for suffix in LEGACY_SUFFIXES)
    dir_tokens = tuple(token.strip("_") for token in LEGACY_SUFFIXES)
    forbidden_parts = tuple(f"/{token}/" for token in dir_tokens) + tuple(
        f"\\{token}\\" for token in dir_tokens
    )
    forbidden_prefixes = tuple(f"{token}/" for token in dir_tokens) + tuple(
        f"{token}\\" for token in dir_tokens
    )
    return forbidden_suffixes, forbidden_parts, forbidden_prefixes


def _has_legacy_pattern(
    lowered_path: str,
    patterns: Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]],
) -> bool:
    """Check if a lowercased path contains any legacy patterns."""
    forbidden_suffixes, forbidden_parts, forbidden_prefixes = patterns
    if any(suffix in lowered_path for suffix in forbidden_suffixes):
        return True
    if any(part in lowered_path for part in forbidden_parts):
        return True
    if any(lowered_path.startswith(prefix) for prefix in forbidden_prefixes):
        return True
    return False


def collect_legacy_modules() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []
    patterns = _build_legacy_patterns()
    for ctx in iter_module_contexts():
        if ctx.rel_path.startswith(("scripts/", "ci_runtime/", "vendor/")):
            continue
        lowered = ctx.rel_path.lower()
        if _has_legacy_pattern(lowered, patterns):
            records.append((ctx.rel_path, 1, "legacy module path"))
    return records


def collect_legacy_configs() -> List[Tuple[str, int, str]]:
    records: List[Tuple[str, int, str]] = []
    config_root = ROOT / "config"
    if not config_root.exists():
        return records
    for path in config_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in CONFIG_EXTENSIONS:
            continue
        try:
            lines = path.read_text().splitlines()
        except UnicodeDecodeError:
            continue
        rel_path = normalize_path(path)
        for lineno, line in enumerate(lines, start=1):
            lower = line.lower()
            if any(token in lower for token in LEGACY_CONFIG_TOKENS):
                records.append((rel_path, lineno, "legacy toggle in config"))
    return records


__all__ = [
    "scan_keywords",
    "collect_flagged_tokens",
    "collect_suppressions",
    "collect_legacy_modules",
    "collect_legacy_configs",
]
