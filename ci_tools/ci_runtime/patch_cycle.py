"""Patch iteration helpers for the CI workflow."""

from __future__ import annotations

from typing import Optional, Set

from .codex import (
    extract_unified_diff,
    has_unified_diff_header,
    request_codex_patch,
)
from .models import (
    FailureContext,
    PatchApplyError,
    PatchAttemptState,
    PatchLifecycleAbort,
    RuntimeOptions,
)
from .patching import apply_patch, patch_looks_risky
from .process import gather_git_diff, gather_git_status


def _obtain_patch_diff(
    *,
    args,
    options: RuntimeOptions,
    failure_ctx: FailureContext,
    iteration: int,
    git_status: str,
    git_diff: str,
    state: PatchAttemptState,
) -> str:
    response = request_codex_patch(
        model=options.model_name,
        reasoning_effort=options.reasoning_effort,
        command=args.command,
        log_excerpt=failure_ctx.log_excerpt,
        summary=failure_ctx.summary,
        focused_diff=failure_ctx.focused_diff,
        git_diff=git_diff,
        git_status=git_status,
        iteration=iteration,
        patch_error=state.last_error,
        attempt=state.patch_attempt,
    )
    diff_text = extract_unified_diff(response or "")
    if not diff_text:
        raise PatchLifecycleAbort.missing_patch()
    return diff_text


def _validate_patch_candidate(
    diff_text: str,
    *,
    seen_patches: Set[str],
    max_patch_lines: int,
) -> Optional[str]:
    if diff_text in seen_patches:
        return "Duplicate patch received; provide an alternative diff."
    seen_patches.add(diff_text)
    if not has_unified_diff_header(diff_text):
        return "Patch missing unified diff headers (diff --git/---/+++ lines)."
    is_risky, reason = patch_looks_risky(diff_text, max_lines=max_patch_lines)
    if is_risky:
        return reason or "Patch failed safety checks."
    return None


def _apply_patch_candidate(
    diff_text: str,
    *,
    state: PatchAttemptState,
) -> bool:
    try:
        apply_patch(diff_text)
    except PatchApplyError as exc:
        state.record_failure(str(exc), retryable=exc.retryable)
        return False
    except RuntimeError as exc:  # pragma: no cover - defensive fallback
        state.record_failure(str(exc), retryable=False)
        return False
    state.last_error = None
    return True


def _should_apply_patch(
    *,
    approval_mode: str,
    attempt: int,
) -> bool:
    if approval_mode == "auto":
        print(f"[codex] Auto-approving patch attempt {attempt}.")
        return True
    decision = (
        input(f"[prompt] Apply patch attempt {attempt}? [y]es/[n]o/[q]uit: ")
        .strip()
        .lower()
    )
    if decision in {"q", "quit"}:
        raise PatchLifecycleAbort.user_declined()
    return decision in {"y", "yes", ""}  # treat empty input as yes


def request_and_apply_patches(
    *,
    args,
    options: RuntimeOptions,
    failure_ctx: FailureContext,
    iteration: int,
    git_status: str,
    git_diff: str,
    seen_patches: Set[str],
) -> None:
    state = PatchAttemptState(max_attempts=args.patch_retries + 1)
    while True:
        state.ensure_budget()
        print(f"[codex] Requesting patch attempt {state.patch_attempt}...")
        diff_text = _obtain_patch_diff(
            args=args,
            options=options,
            failure_ctx=failure_ctx,
            iteration=iteration,
            git_status=git_status,
            git_diff=git_diff,
            state=state,
        )
        validation_error = _validate_patch_candidate(
            diff_text,
            seen_patches=seen_patches,
            max_patch_lines=args.max_patch_lines,
        )
        if validation_error:
            state.record_failure(validation_error, retryable=True)
            continue
        if not _should_apply_patch(
            approval_mode=options.patch_approval_mode,
            attempt=state.patch_attempt,
        ):
            state.record_failure("User declined to apply the patch.", retryable=True)
            continue
        if _apply_patch_candidate(diff_text, state=state):
            post_status = gather_git_status()
            if post_status:
                print("[info] git status after patch:")
                print(post_status)
            else:
                print("[info] Working tree is clean after applying patch.")
            return
        git_status = gather_git_status()
        git_diff = gather_git_diff(staged=False)


__all__ = ["request_and_apply_patches"]
