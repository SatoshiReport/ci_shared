"""CI automation workflow orchestration."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path
from typing import Iterable, Optional, Set

from .config import (
    DEFAULT_REASONING_EFFORT,
    REASONING_EFFORT_CHOICES,
    REQUIRED_MODEL,
)
from .coverage import extract_coverage_deficits
from .environment import load_env_settings
from .failures import build_failure_context
from .messaging import commit_and_push, request_commit_message
from .models import (
    CiAbort,
    ModelSelectionAbort,
    PatchLifecycleAbort,
    ReasoningEffortAbort,
    RuntimeOptions,
)
from .patch_cycle import request_and_apply_patches
from .process import gather_git_diff, gather_git_status, run_command


def _resolve_model_choice(model_arg: Optional[str]) -> str:
    candidate = model_arg or os.environ.get("OPENAI_MODEL") or REQUIRED_MODEL
    if candidate != REQUIRED_MODEL:
        raise ModelSelectionAbort.unsupported_model(
            received=candidate, required=REQUIRED_MODEL
        )
    os.environ["OPENAI_MODEL"] = candidate
    return candidate


def _resolve_reasoning_choice(reasoning_arg: Optional[str]) -> str:
    env_reasoning = os.environ.get("OPENAI_REASONING_EFFORT")
    candidate = (
        reasoning_arg
        or (env_reasoning.lower() if env_reasoning else None)
        or DEFAULT_REASONING_EFFORT
    )
    if candidate not in REASONING_EFFORT_CHOICES:
        raise ReasoningEffortAbort.unsupported_choice(
            received=candidate, allowed=REASONING_EFFORT_CHOICES
        )
    os.environ["OPENAI_REASONING_EFFORT"] = candidate
    return candidate


def _derive_runtime_flags(
    args: argparse.Namespace, command_tokens: list[str]
) -> tuple[bool, dict[str, str], bool, bool, bool]:
    command_basename = Path(command_tokens[0]).name if command_tokens else ""
    automation_mode = command_basename == "ci.sh"
    command_env = {"CI_AUTOMATION": "1"} if automation_mode else {}
    auto_stage_enabled = args.auto_stage or automation_mode
    commit_message_enabled = args.commit_message or automation_mode
    auto_push_enabled = automation_mode
    return (
        automation_mode,
        command_env,
        auto_stage_enabled,
        commit_message_enabled,
        auto_push_enabled,
    )


def configure_runtime(args: argparse.Namespace) -> RuntimeOptions:
    load_env_settings(args.env_file)
    command_tokens = shlex.split(args.command)
    model_name = _resolve_model_choice(args.model)
    reasoning_effort = _resolve_reasoning_choice(args.reasoning_effort)
    (
        automation_mode,
        command_env,
        auto_stage_enabled,
        commit_message_enabled,
        auto_push_enabled,
    ) = _derive_runtime_flags(args, command_tokens)

    return RuntimeOptions(
        command_tokens=command_tokens,
        command_env=command_env,
        patch_approval_mode=args.patch_approval_mode,
        automation_mode=automation_mode,
        auto_stage_enabled=auto_stage_enabled,
        commit_message_enabled=commit_message_enabled,
        auto_push_enabled=auto_push_enabled,
        model_name=model_name,
        reasoning_effort=reasoning_effort,
    )


def perform_dry_run(args: argparse.Namespace, options: RuntimeOptions) -> Optional[int]:
    if not args.dry_run:
        return None
    print("[info] Dry run: executing CI command once without invoking Codex.")
    result = run_command(options.command_tokens, live=True, env=options.command_env)
    return result.returncode


def _collect_worktree_diffs() -> tuple[str, str]:
    return gather_git_diff(staged=False), gather_git_diff(staged=True)


def _worktree_is_clean(unstaged_diff: str, staged_diff: str) -> bool:
    return not unstaged_diff and not staged_diff


def _stage_if_needed(options: RuntimeOptions, staged_diff: str) -> str:
    if not options.auto_stage_enabled:
        return staged_diff
    print("[info] Staging all changes (`git add -A`).")
    run_command(["git", "add", "-A"], check=True)
    return gather_git_diff(staged=True)


def _warn_missing_staged_changes() -> None:
    print(
        "[warn] No staged changes detected. Stage files before requesting a commit message.",
        file=sys.stderr,
    )


def _maybe_request_commit_message(
    options: RuntimeOptions,
    staged_diff: str,
    extra_context: str,
) -> tuple[Optional[str], list[str]]:
    if not options.commit_message_enabled:
        return None, []
    summary, body_lines = request_commit_message(
        model=options.model_name,
        reasoning_effort=options.reasoning_effort,
        staged_diff=staged_diff,
        extra_context=extra_context,
        detailed=options.auto_push_enabled,
    )
    preview_lines: list[str] = [summary]
    if body_lines:
        preview_lines.append("")
        preview_lines.extend(body_lines)
    print("[info] Suggested commit message:")
    for line in preview_lines:
        print(f"    {line}" if line else "")
    return summary, body_lines


def _maybe_push_or_notify(
    options: RuntimeOptions,
    summary: Optional[str],
    body_lines: list[str],
) -> None:
    if options.auto_push_enabled:
        commit_summary = summary or "Automated commit"
        commit_body = body_lines if summary is not None else []
        commit_and_push(commit_summary, commit_body, push=True)
        return
    if summary is not None:
        print("[info] Commit message ready; run `git commit` manually if desired.")


def finalize_worktree(args: argparse.Namespace, options: RuntimeOptions) -> int:
    unstaged_diff, staged_diff = _collect_worktree_diffs()
    if _worktree_is_clean(unstaged_diff, staged_diff):
        print("[info] Working tree clean. Nothing to stage or commit.")
        return 0

    staged_diff = _stage_if_needed(options, staged_diff)
    if not staged_diff:
        _warn_missing_staged_changes()
        return 0

    summary, body_lines = _maybe_request_commit_message(
        options, staged_diff, args.commit_extra_context
    )
    _maybe_push_or_notify(options, summary, body_lines)
    return 0


def run_repair_iterations(args: argparse.Namespace, options: RuntimeOptions) -> None:
    seen_patches: Set[str] = set()
    for iteration in range(1, args.max_iterations + 1):
        print(f"[loop] Iteration {iteration} — running `{args.command}`")
        result = run_command(options.command_tokens, live=True, env=options.command_env)
        coverage_report = (
            extract_coverage_deficits(result.combined_output) if result.ok else None
        )
        if result.ok and coverage_report is None:
            print(f"[loop] CI command succeeded on iteration {iteration}.")
            return
        failure_ctx = build_failure_context(args, result, coverage_report)
        git_status = gather_git_status()
        git_diff = gather_git_diff(staged=False)
        request_and_apply_patches(
            args=args,
            options=options,
            failure_ctx=failure_ctx,
            iteration=iteration,
            git_status=git_status,
            git_diff=git_diff,
            seen_patches=seen_patches,
        )
    raise PatchLifecycleAbort.attempts_exhausted()


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Automate CI fixes via Codex.")
    parser.add_argument(
        "--command",
        default="./scripts/ci.sh",
        help="Command to run for CI (default: %(default)s)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        help="Maximum Codex-assisted fix attempts (default: %(default)s)",
    )
    parser.add_argument(
        "--log-tail",
        type=int,
        default=200,
        help="Number of log lines from the failure to send to Codex (default: %(default)s)",
    )
    parser.add_argument(
        "--model",
        help=f"Codex model name (default/required: {REQUIRED_MODEL})",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=REASONING_EFFORT_CHOICES,
        help=(
            "Reasoning effort hint for Codex " f"(default: {DEFAULT_REASONING_EFFORT})"
        ),
    )
    parser.add_argument(
        "--max-patch-lines",
        type=int,
        default=1500,
        help="Abort if Codex suggests touching more than this many lines (default: %(default)s)",
    )
    parser.add_argument(
        "--patch-approval-mode",
        choices=("prompt", "auto"),
        default="prompt",
        help=(
            "Control whether patch application requires approval "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--auto-stage",
        action="store_true",
        help="After CI passes, run `git add -A` before asking for a commit message.",
    )
    parser.add_argument(
        "--commit-message",
        action="store_true",
        help="Request a commit message from Codex after CI succeeds.",
    )
    parser.add_argument(
        "--commit-extra-context",
        default="",
        help="Additional instructions for the commit message prompt.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the CI command once and exit without contacting Codex.",
    )
    parser.add_argument(
        "--env-file",
        default="~/.env",
        help="Path to dotenv file for Codex CLI environment defaults (default: %(default)s)",
    )
    parser.add_argument(
        "--patch-retries",
        type=int,
        default=1,
        help="Number of additional patch attempts when apply fails (default: %(default)s)",
    )
    parsed_args = list(argv) if argv is not None else None
    return parser.parse_args(parsed_args)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    options = configure_runtime(args)
    try:
        dry_run_exit = perform_dry_run(args, options)
        if dry_run_exit is not None:
            return dry_run_exit
        run_repair_iterations(args, options)
    except KeyboardInterrupt:
        print("\n[info] Received Ctrl-C. Aborting ci.py cleanly.")
        return 130
    except CiAbort as exc:
        if exc.detail:
            print(f"[error] {exc.detail}", file=sys.stderr)
        return exc.exit_code
    return finalize_worktree(args, options)


__all__ = [
    "main",
    "configure_runtime",
    "perform_dry_run",
    "run_repair_iterations",
    "finalize_worktree",
]
