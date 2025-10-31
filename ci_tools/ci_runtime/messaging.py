"""Commit message and git commit helpers."""

from __future__ import annotations

import os
import subprocess
import textwrap
from typing import List, Optional

from .codex import invoke_codex
from .models import CommitMessageError, GitCommandAbort
from .process import run_command


def request_commit_message(
    *,
    model: str,
    reasoning_effort: Optional[str],
    staged_diff: str,
    extra_context: str,
    detailed: bool = False,
) -> tuple[str, List[str]]:
    effort_display = reasoning_effort or "default"
    if detailed:
        instructions = textwrap.dedent(
            """\
            Produce a git commit message consisting of:
            - A concise subject line (≤72 characters) that summarizes what changed using past tense.
            - After a blank line, a short bullet list (five bullets or fewer, each starting with "- ") that highlights key changes using past tense.
            Avoid trailing periods on the subject line.
            Rely on the diff provided below for context and do not run shell commands such as `diff --git`.
            """
        )
    else:
        instructions = (
            "Provide a single-line commit message in past tense (no trailing punctuation). "
            "Use the diff shown above for context instead of executing shell commands like `diff --git`."
        )
    extra_block = extra_context.strip()
    prompt = textwrap.dedent(
        f"""\
        You write high-quality git commit messages.

        Model configuration:
        - Model: {model}
        - Reasoning effort: {effort_display}

        Diff for the staged changes:
        ```diff
        {staged_diff or '/* no staged diff */'}
        ```

        {instructions}
        {extra_block}
        """
    ).strip()
    response = invoke_codex(
        prompt,
        model=model,
        description="commit message suggestion",
        reasoning_effort=reasoning_effort,
    )
    lines = [line.rstrip() for line in response.strip().splitlines()]
    if not lines:
        raise CommitMessageError.empty_response()
    summary = lines[0].strip()
    body_lines = lines[1:]
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    return summary, body_lines


def commit_and_push(
    summary: str,
    body_lines: List[str],
    *,
    push: bool,
) -> None:
    print("[info] Creating commit...")
    commit_args = ["git", "commit", "-m", summary]
    body_text = "\n".join(body_lines).strip()
    if body_text:
        commit_args.extend(["-m", body_text])
    try:
        run_command(commit_args, check=True, live=True)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
        raise GitCommandAbort.commit_failed(exc) from exc

    if not push:
        return

    remote = os.environ.get("GIT_REMOTE", "origin")
    branch_result = run_command(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], check=True
    )
    branch = branch_result.stdout.strip()
    print(f"[info] Pushing to {remote}/{branch}...")
    try:
        run_command(["git", "push", remote, branch], check=True, live=True)
    except subprocess.CalledProcessError as exc:  # pragma: no cover - defensive
        raise GitCommandAbort.push_failed(exc) from exc


__all__ = ["request_commit_message", "commit_and_push"]
