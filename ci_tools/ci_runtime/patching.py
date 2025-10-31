"""Patch safety checks and application helpers."""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from .codex import risky_pattern_in_diff, truncate_diff_summary
from .config import PROTECTED_PATH_PREFIXES
from .models import PatchApplyError


def _extract_diff_paths(patch_text: str) -> set[str]:
    protected_paths: set[str] = set()
    for line in patch_text.splitlines():
        if not line.startswith("diff --git"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        candidates = (parts[2][2:], parts[3][2:])
        for candidate in candidates:
            if candidate.startswith(PROTECTED_PATH_PREFIXES):
                protected_paths.add(candidate)
    return protected_paths


def patch_looks_risky(patch_text: str, *, max_lines: int) -> tuple[bool, Optional[str]]:
    if not patch_text:
        msg = "Patch content was empty."
        return True, msg

    exceeds_limit, limit_reason = truncate_diff_summary(patch_text, max_lines)
    if exceeds_limit:
        return True, limit_reason

    protected_paths = _extract_diff_paths(patch_text)
    if protected_paths:
        offending = ", ".join(sorted(protected_paths))
        return True, f"Patch attempted to modify protected path `{offending}`."

    pattern = risky_pattern_in_diff(patch_text)
    if pattern:
        return True, f"Patch matched risky pattern: {pattern}"

    return False, None


def _ensure_trailing_newline(patch_text: str) -> str:
    return patch_text if patch_text.endswith("\n") else f"{patch_text}\n"


def _apply_patch_with_git(patch_text: str) -> tuple[bool, str]:
    git_check = subprocess.run(
        ["git", "apply", "--check", "--whitespace=nowarn"],
        input=patch_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    check_output = (git_check.stdout or "") + (git_check.stderr or "")
    if git_check.returncode != 0:
        return False, check_output
    git_apply = subprocess.run(
        ["git", "apply", "--allow-empty", "--whitespace=nowarn"],
        input=patch_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if git_apply.returncode != 0:
        output = (git_apply.stdout or "") + (git_apply.stderr or "")
        raise PatchApplyError.git_apply_failed(output=output)
    if git_apply.stdout:
        print(git_apply.stdout.rstrip())
    return True, check_output


def _patch_already_applied(patch_text: str) -> bool:
    git_reverse_check = subprocess.run(
        ["git", "apply", "--check", "--reverse", "--whitespace=nowarn"],
        input=patch_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if git_reverse_check.returncode == 0:
        print("[info] Patch already applied according to `git apply`; skipping.")
        return True
    return False


def _apply_patch_with_patch_tool(
    patch_text: str,
    *,
    check_output: str,
) -> None:
    env = dict(os.environ)
    env.setdefault("PATCH_CREATE_BACKUP", "no")
    dry_run_cmd = [
        "patch",
        "--batch",
        "--forward",
        "--reject-file=-",
        "-p1",
        "--dry-run",
    ]
    dry_run = subprocess.run(
        dry_run_cmd,
        input=patch_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if dry_run.returncode != 0:
        dry_output = (dry_run.stdout or "") + (dry_run.stderr or "")
        raise PatchApplyError.preflight_failed(
            check_output=check_output,
            dry_output=dry_output,
        )

    apply_cmd = ["patch", "--batch", "--forward", "--reject-file=-", "-p1"]
    actual = subprocess.run(
        apply_cmd,
        input=patch_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if actual.returncode != 0:
        output = (actual.stdout or "") + (actual.stderr or "")
        raise PatchApplyError.patch_exit(returncode=actual.returncode, output=output)
    if actual.stdout:
        print(actual.stdout.rstrip())


def apply_patch(patch_text: str) -> None:
    normalized = _ensure_trailing_newline(patch_text)
    applied, check_output = _apply_patch_with_git(normalized)
    if applied:
        return
    if _patch_already_applied(normalized):
        return
    _apply_patch_with_patch_tool(normalized, check_output=check_output)


__all__ = ["patch_looks_risky", "apply_patch"]
