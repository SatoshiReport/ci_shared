"""Codex CLI interaction helpers."""

from __future__ import annotations

import re
import subprocess
import textwrap
import threading
from typing import Optional

from .config import RISKY_PATTERNS
from .models import CodexCliError
from .process import log_codex_interaction


def build_codex_command(model: str, reasoning_effort: Optional[str]) -> list[str]:
    command = ["codex", "exec", "--model", model, "-"]
    if reasoning_effort:
        command.insert(-1, "-c")
        command.insert(-1, f"model_reasoning_effort={reasoning_effort}")
    return command


def _feed_prompt(process: subprocess.Popen[str], prompt: str) -> None:
    try:
        if process.stdin:
            process.stdin.write(prompt)
            process.stdin.close()
    except BrokenPipeError:  # pragma: no cover - defensive
        pass


def _stream_output(process: subprocess.Popen[str]) -> tuple[list[str], list[str]]:
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _pump(pipe, collector: list[str]) -> None:
        try:
            for line in iter(pipe.readline, ""):
                collector.append(line)
        finally:
            pipe.close()

    threads: list[threading.Thread] = []
    if process.stdout:
        threads.append(
            threading.Thread(
                target=_pump, args=(process.stdout, stdout_lines), daemon=True
            )
        )
        threads[-1].start()
    if process.stderr:
        threads.append(
            threading.Thread(
                target=_pump, args=(process.stderr, stderr_lines), daemon=True
            )
        )
        threads[-1].start()

    for thread in threads:
        thread.join()
    return stdout_lines, stderr_lines


def invoke_codex(
    prompt: str,
    *,
    model: str,
    description: str,
    reasoning_effort: Optional[str],
) -> str:
    command = build_codex_command(model, reasoning_effort)
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    feeder = threading.Thread(target=_feed_prompt, args=(process, prompt), daemon=True)
    feeder.start()
    feeder.join()

    stdout_lines, stderr_lines = _stream_output(process)
    returncode = process.wait()
    stdout = "".join(stdout_lines).strip()
    stderr = "".join(stderr_lines).strip()

    log_codex_interaction(description, prompt, stdout or stderr)

    if returncode != 0:
        error_details = stderr or stdout
        raise CodexCliError.exit_status(returncode=returncode, output=error_details)

    if stdout.startswith("assistant:"):
        stdout = stdout.partition("\n")[2].strip()
    return stdout or stderr


def truncate_error(error: Optional[str], limit: int = 2000) -> str:
    if not error:
        return "(none)"
    text = error.strip()
    if len(text) > limit:
        return text[:limit] + "...(truncated)"
    return text


def extract_unified_diff(response_text: str) -> Optional[str]:
    if not response_text:
        return None
    if response_text.strip().upper() == "NOOP":
        return None
    code_blocks = re.findall(r"```(?:diff)?\s*(.*?)```", response_text, flags=re.DOTALL)
    if code_blocks:
        for block in code_blocks:
            text = block.strip()
            if text.startswith(("diff", "---", "Index:", "From ")):
                return text
        return code_blocks[0].strip()
    return response_text


def has_unified_diff_header(diff_text: str) -> bool:
    return bool(re.search(r"^(diff --git|--- |\+\+\+ )", diff_text, re.MULTILINE))


def request_codex_patch(
    *,
    model: str,
    reasoning_effort: str,
    command: str,
    log_excerpt: str,
    summary: str,
    focused_diff: str,
    git_diff: str,
    git_status: str,
    iteration: int,
    patch_error: Optional[str],
    attempt: int,
) -> str:
    prompt = textwrap.dedent(
        f"""\
        You are currently iterating on automated CI repairs.

        Context:
        - CI command: `{command}`
        - Iteration: {iteration}
        - Patch attempt: {attempt}
        - Git status:
        {git_status or '(clean)'}

        Failure summary:
        {summary or '(not detected)'}

        Focused diff for implicated files:
        ```diff
        {focused_diff or '/* no focused diff */'}
        ```

        Current diff (unstaged working tree):
        ```diff
        {git_diff or '/* no diff */'}
        ```

        Latest CI failure log (tail):
        ```
        {log_excerpt}
        ```

        Previous patch apply error:
        {truncate_error(patch_error)}

        Instructions:
        - Respond ONLY with a unified diff (include `diff --git`, `---`, and `+++` lines) that can be applied with `patch -p1`.
        - Avoid large-scale refactors; keep the change tightly scoped to resolve the failure.
        - If no code change is appropriate, reply with `NOOP`.
        - Do not modify automation scaffolding (ci.py, ci_tools/*, scripts/ci.sh).
        """
    )
    return invoke_codex(
        prompt,
        model=model,
        description="patch suggestion",
        reasoning_effort=reasoning_effort,
    )


def truncate_diff_summary(
    diff_text: str, line_limit: int
) -> tuple[bool, Optional[str]]:
    changed_lines = sum(
        1 for line in diff_text.splitlines() if line.startswith(("+", "-"))
    )
    if changed_lines > line_limit:
        return (
            True,
            f"Patch has {changed_lines} changed lines which exceeds the limit of {line_limit}.",
        )
    return False, None


def risky_pattern_in_diff(diff_text: str) -> Optional[str]:
    for pattern in RISKY_PATTERNS:
        if pattern.search(diff_text):
            return pattern.pattern
    return None


__all__ = [
    "build_codex_command",
    "invoke_codex",
    "request_codex_patch",
    "truncate_error",
    "extract_unified_diff",
    "has_unified_diff_header",
    "truncate_diff_summary",
    "risky_pattern_in_diff",
]
