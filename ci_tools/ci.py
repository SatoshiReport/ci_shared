"""Compatibility layer re-exporting the CI runtime helpers.

This module provides backward compatibility by re-exporting all public symbols
from ci_runtime. This allows consumers to import from either:
    - ci_tools.ci (stable legacy API surface)
    - ci_tools.ci_runtime (current canonical location)

The ci_runtime package is the canonical source of implementation. This file exists
solely to maintain import compatibility for existing consumers (Zeus, Kalshi).

Usage:
    from ci_tools.ci import main, configure_runtime  # Legacy compatible
    from ci_tools.ci_runtime import main, configure_runtime  # Canonical
"""

from __future__ import annotations

from .ci_runtime import (
    PatchPrompt,
    apply_patch,
    build_codex_command,
    build_failure_context,
    commit_and_push,
    configure_runtime,
    extract_coverage_deficits,
    extract_unified_diff,
    finalize_worktree,
    gather_file_diff,
    gather_git_diff,
    gather_git_diff_limited,
    gather_git_status,
    has_unified_diff_header,
    invoke_codex,
    log_codex_interaction,
    main,
    patch_looks_risky,
    perform_dry_run,
    request_and_apply_patches,
    request_codex_patch,
    request_commit_message,
    run_command,
    run_repair_iterations,
    tail_text,
    truncate_diff_summary,
    truncate_error,
)

__all__ = [
    "apply_patch",
    "build_codex_command",
    "build_failure_context",
    "commit_and_push",
    "configure_runtime",
    "extract_coverage_deficits",
    "extract_unified_diff",
    "finalize_worktree",
    "gather_file_diff",
    "gather_git_diff",
    "gather_git_diff_limited",
    "gather_git_status",
    "has_unified_diff_header",
    "invoke_codex",
    "log_codex_interaction",
    "main",
    "patch_looks_risky",
    "perform_dry_run",
    "request_and_apply_patches",
    "request_codex_patch",
    "request_commit_message",
    "run_command",
    "run_repair_iterations",
    "tail_text",
    "truncate_diff_summary",
    "truncate_error",
    "PatchPrompt",
]
