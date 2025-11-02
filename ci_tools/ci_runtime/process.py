"""Process and git helpers for CI runtime."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Iterable, Optional

from .models import CommandResult


def _run_command_buffered(
    args: list[str],
    *,
    check: bool,
    env: dict[str, str],
) -> CommandResult:
    """Run a subprocess and capture its output without streaming."""
    process = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        check=False,
    )
    if check and process.returncode != 0:
        raise subprocess.CalledProcessError(
            process.returncode,
            process.args,
            output=process.stdout,
            stderr=process.stderr,
        )
    return CommandResult(
        returncode=process.returncode,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def _stream_pipe(pipe, collector: list[str], target) -> None:
    """Collect text from a pipe while forwarding it to the provided stream."""
    try:
        for line in iter(pipe.readline, ""):
            collector.append(line)
            target.write(line)
            target.flush()
    finally:
        pipe.close()


def _run_command_streaming(
    args: list[str],
    *,
    check: bool,
    env: dict[str, str],
) -> CommandResult:
    """Stream stdout/stderr live while accumulating the full text."""
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    with subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    ) as process:
        threads: list[threading.Thread] = []

        if process.stdout:
            threads.append(
                threading.Thread(
                    target=_stream_pipe,
                    args=(process.stdout, stdout_lines, sys.stdout),
                    daemon=True,
                )
            )
        if process.stderr:
            threads.append(
                threading.Thread(
                    target=_stream_pipe,
                    args=(process.stderr, stderr_lines, sys.stderr),
                    daemon=True,
                )
            )

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        returncode = process.wait()
    stdout_text = "".join(stdout_lines)
    stderr_text = "".join(stderr_lines)

    if check and returncode != 0:
        raise subprocess.CalledProcessError(
            returncode, process.args, output=stdout_text, stderr=stderr_text
        )

    return CommandResult(
        returncode=returncode,
        stdout=stdout_text,
        stderr=stderr_text,
    )


def run_command(
    args: Iterable[str],
    *,
    check: bool = False,
    live: bool = False,
    env: Optional[dict[str, str]] = None,
) -> CommandResult:
    """Run a command, optionally streaming output while capturing it."""
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    command_args = list(args)
    runner = _run_command_streaming if live else _run_command_buffered
    return runner(
        command_args,
        check=check,
        env=merged_env,
    )


def tail_text(text: str, lines: int) -> str:
    """Return the last *lines* lines from the provided multiline string."""
    return "\n".join(text.splitlines()[-lines:])


def gather_git_diff(*, staged: bool = False) -> str:
    """Return the git diff for staged or unstaged changes."""
    args = ["git", "diff", "--cached"] if staged else ["git", "diff"]
    result = run_command(args)
    return result.stdout


def gather_git_status() -> str:
    """Return a short git status suitable for prompt summaries."""
    result = run_command(["git", "status", "--short"])
    return result.stdout.strip()


def gather_file_diff(path: str) -> str:
    """Return the diff for a single path relative to HEAD."""
    result = run_command(["git", "diff", path])
    return result.stdout


def log_codex_interaction(kind: str, prompt: str, response: str) -> None:
    """Append the interaction to logs/codex_ci.log for later auditing."""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "codex_ci.log"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"--- {kind} ---\n")
        handle.write("Prompt:\n")
        handle.write(prompt.strip() + "\n")
        handle.write("Response:\n")
        handle.write(response.strip() + "\n\n")


__all__ = [
    "run_command",
    "tail_text",
    "gather_git_diff",
    "gather_git_status",
    "gather_file_diff",
    "log_codex_interaction",
]
