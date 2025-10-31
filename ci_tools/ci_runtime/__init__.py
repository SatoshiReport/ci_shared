"""Public API for the Codex CI runtime package."""

from __future__ import annotations

from .codex import (
    build_codex_command,
    extract_unified_diff,
    has_unified_diff_header,
    invoke_codex,
    request_codex_patch,
    risky_pattern_in_diff,
    truncate_diff_summary,
    truncate_error,
)
from .coverage import extract_coverage_deficits
from .failures import build_failure_context
from .messaging import commit_and_push, request_commit_message
from .patch_cycle import request_and_apply_patches
from .patching import apply_patch, patch_looks_risky
from .process import (
    gather_file_diff,
    gather_git_diff,
    gather_git_status,
    log_codex_interaction,
    run_command,
    tail_text,
)
from .workflow import (
    configure_runtime,
    finalize_worktree,
    main,
    perform_dry_run,
    run_repair_iterations,
)

__all__ = [
    "configure_runtime",
    "perform_dry_run",
    "run_repair_iterations",
    "finalize_worktree",
    "main",
    "request_commit_message",
    "commit_and_push",
    "run_command",
    "tail_text",
    "gather_git_diff",
    "gather_git_status",
    "gather_file_diff",
    "log_codex_interaction",
    "build_codex_command",
    "invoke_codex",
    "request_codex_patch",
    "truncate_error",
    "extract_unified_diff",
    "has_unified_diff_header",
    "truncate_diff_summary",
    "risky_pattern_in_diff",
    "patch_looks_risky",
    "apply_patch",
    "extract_coverage_deficits",
    "build_failure_context",
    "request_and_apply_patches",
]
