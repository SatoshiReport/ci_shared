#!/usr/bin/env python3
"""Automated CI fixer that collaborates with Codex to keep iterating until the
existing shell pipeline succeeds and then drafts a commit message.

Usage overview
--------------
Run the script from the repository root:

    ./ci.py --model gpt-5-codex --reasoning-effort high

Key capabilities:
* Runs `scripts/ci.sh` (or a custom command) and captures stdout/stderr.
* On failure, sends the tail of the log plus the current git diff/status to
  Codex, requesting a unified diff patch to apply.
* Applies the suggested patch in-place and loops until CI succeeds or a safety
  guard triggers, pausing for your approval before touching files.
* Once CI passes, optionally stages changes and asks Codex for an imperative
  commit message based on the staged diff.

By default the script uses `gpt-5-codex` with `high` reasoning effort; provide
`--model gpt-5-codex` and/or `--reasoning-effort {low,medium,high}` (or export
`OPENAI_MODEL` / `OPENAI_REASONING_EFFORT`) explicitly if you prefer, but any
other model choice causes the run to abort.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
import threading
from dataclasses import dataclass
from typing import Iterable, Optional

from pathlib import Path


def detect_repo_root() -> Path:
    """Best-effort detection of the repository root."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        candidate = Path(result.stdout.strip())
        if candidate.exists():
            return candidate
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return Path.cwd()


CONFIG_CANDIDATES = ('ci_shared.config.json', '.ci_shared.config.json')


def load_repo_config(repo_root: Path) -> dict[str, object]:
    """Load shared CI configuration when available."""
    for relative in CONFIG_CANDIDATES:
        candidate = repo_root / relative
        if not candidate.is_file():
            continue
        try:
            with candidate.open('r', encoding='utf-8') as handle:
                data = json.load(handle)
        except json.JSONDecodeError:
            print(f'[warning] Failed to parse {candidate}; using defaults.', file=sys.stderr)
            continue
        if isinstance(data, dict):
            return data
    return {}


# Default context describing the repository so Codex has enough framing to propose
# targeted fixes without having to rediscover basic project facts.
REPO_ROOT = detect_repo_root()
REPO_CONFIG = load_repo_config(REPO_ROOT)

DEFAULT_REPO_CONTEXT = textwrap.dedent(
    """\
    You are assisting with continuous integration fixes for this repository.
    Repository facts:
    - Python 3.10+ project using PEP 8 conventions and four-space indentation.
    - Source lives under src/, tests mirror that structure under tests/.
    - Avoid committing secrets, install dependencies via scripts/requirements.txt when needed,
      and prefer focused edits rather than sweeping rewrites.
    When CI fails, respond with a unified diff (a/ b/ prefixes) that can be applied with
    `patch -p1`. Keep the patch minimal, and mention any follow-up steps if the fix
    requires manual verification.
    """
)

REPO_CONTEXT = textwrap.dedent(
    REPO_CONFIG.get('repo_context', DEFAULT_REPO_CONTEXT)
).strip()

# Safety heuristics: quick checks to reject obviously dangerous patches before they
# touch the working tree. This is not exhaustive but offers guardrails.
RISKY_PATTERNS = (
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r"rm\s+-rf"),
    re.compile(r"subprocess\.run\([^)]*['\"]rm['\"]"),
)

DEFAULT_PROTECTED_PATH_PREFIXES: tuple[str, ...] = (
    "ci.py",
    "ci_tools/",
    "scripts/ci.sh",
)

PROTECTED_PATH_PREFIXES: tuple[str, ...] = tuple(
    str(item) for item in REPO_CONFIG.get('protected_path_prefixes', DEFAULT_PROTECTED_PATH_PREFIXES)
)

REQUIRED_MODEL = "gpt-5-codex"
REASONING_EFFORT_CHOICES: tuple[str, ...] = ("low", "medium", "high")
DEFAULT_REASONING_EFFORT = "high"
COVERAGE_THRESHOLD = float(REPO_CONFIG.get('coverage_threshold', 80.0))

IMPORT_ERROR_PATTERN = re.compile(
    r"ImportError: cannot import name '([^']+)' from '([^']+)'"
)
ATTRIBUTE_ERROR_PATTERN = re.compile(
    r"AttributeError:\s+(?:'[^']+'\s+object\s+has\s+no\s+attribute\s+'([^']+)')"
)


class CiError(RuntimeError):
    """Base class for CI automation runtime failures."""

    default_message = "CI automation failure"

    def __init__(self, *, detail: Optional[str] = None):
        self.detail = detail
        message = self.default_message if detail is None else f"{self.default_message}: {detail}"
        super().__init__(message)


class CodexCliError(CiError):
    """Raised when invoking the Codex CLI returns a non-zero status."""

    default_message = "Codex CLI command failed"

    @classmethod
    def exit_status(cls, *, returncode: int, output: Optional[str]) -> "CodexCliError":
        normalized = (output or "").strip() or "(no output)"
        detail = f"exit status {returncode} ({normalized})"
        return cls(detail=detail)


class CommitMessageError(CiError):
    """Raised when commit message generation produces no content."""

    default_message = "Commit message response was empty"

    @classmethod
    def empty_response(cls) -> "CommitMessageError":
        return cls()


class CiAbort(SystemExit):
    """Base class for deliberate CI workflow exits."""

    default_message = "CI automation aborted"

    def __init__(self, *, detail: Optional[str] = None, code: int = 1):
        self.detail = detail
        self.exit_code = code
        message = self.default_message if detail is None else f"{self.default_message}: {detail}"
        super().__init__(message)
        self.code = code


class GitCommandAbort(CiAbort):
    """Raised when git operations fail during CI automation."""

    default_message = "Git command failed"

    @classmethod
    def commit_failed(cls, exc: subprocess.CalledProcessError) -> "GitCommandAbort":
        output = (exc.stderr or exc.output or "").strip()
        detail = f"'git commit' exited with status {exc.returncode}"
        if output:
            detail = f"{detail}; {output}"
        return cls(detail=detail)

    @classmethod
    def push_failed(cls, exc: subprocess.CalledProcessError) -> "GitCommandAbort":
        output = (exc.stderr or exc.output or "").strip()
        detail = f"'git push' exited with status {exc.returncode}"
        if output:
            detail = f"{detail}; {output}"
        return cls(detail=detail)


class RepositoryStateAbort(CiAbort):
    """Raised when the repository is not in a valid state for CI automation."""

    default_message = "Repository state invalid"

    @classmethod
    def detached_head(cls) -> "RepositoryStateAbort":
        return cls(detail="detached HEAD detected; checkout a branch before running ci.py")


class ModelSelectionAbort(CiAbort):
    """Raised when an unsupported model is provided to the CI workflow."""

    default_message = "Unsupported model configuration"

    @classmethod
    def unsupported_model(cls, *, received: str, required: str) -> "ModelSelectionAbort":
        return cls(detail=f"requires `{required}` but received `{received}`")


class ReasoningEffortAbort(CiAbort):
    """Raised when an unsupported reasoning effort value is supplied."""

    default_message = "Unsupported reasoning effort"

    @classmethod
    def unsupported_choice(cls, *, received: str, allowed: Iterable[str]) -> "ReasoningEffortAbort":
        choices = ", ".join(allowed)
        return cls(detail=f"expected one of {choices}; received `{received}`")


class PatchLifecycleAbort(CiAbort):
    """Raised when the automated patch workflow cannot continue."""

    default_message = "Patch workflow aborted"

    @classmethod
    def attempts_exhausted(cls) -> "PatchLifecycleAbort":
        return cls(detail="unable to obtain a valid patch after multiple attempts")

    @classmethod
    def missing_patch(cls) -> "PatchLifecycleAbort":
        return cls(detail="Codex returned an empty or NOOP patch response")

    @classmethod
    def user_declined(cls) -> "PatchLifecycleAbort":
        return cls(detail="user declined CI automation")

    @classmethod
    def retries_exhausted(cls) -> "PatchLifecycleAbort":
        return cls(detail="Codex patches failed after exhausting retries; manual review required")


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def combined_output(self) -> str:
        return f"{self.stdout}{self.stderr}"


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
    if not live:
        process = subprocess.run(
            list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=merged_env,
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

    process = subprocess.Popen(
        list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=merged_env,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _stream(pipe, collector: list[str], target) -> None:
        try:
            for line in iter(pipe.readline, ""):
                collector.append(line)
                target.write(line)
                target.flush()
        finally:
            pipe.close()

    threads = []
    if process.stdout:
        threads.append(
            threading.Thread(
                target=_stream, args=(process.stdout, stdout_lines, sys.stdout), daemon=True
            )
        )
        threads[-1].start()
    if process.stderr:
        threads.append(
            threading.Thread(
                target=_stream, args=(process.stderr, stderr_lines, sys.stderr), daemon=True
            )
        )
        threads[-1].start()

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


def tail_text(text: str, lines: int) -> str:
    """Return the last `lines` lines from `text`."""
    split = text.splitlines()
    return "\n".join(split[-lines:]) if len(split) > lines else "\n".join(split)


def gather_git_diff(*, staged: bool = False) -> str:
    """Collect the git diff (staged or unstaged)."""
    cmd = ["git", "diff", "--cached"] if staged else ["git", "diff"]
    return run_command(cmd).stdout.strip()


def gather_git_status() -> str:
    return run_command(["git", "status", "--short"]).stdout.strip()


def gather_file_diff(path: str) -> str:
    """Return the diff for a specific file (unstaged)."""
    result = run_command(["git", "diff", "--", path])
    return result.stdout.strip()


def log_codex_interaction(kind: str, prompt: str, response: str) -> None:
    """Persist Codex prompts/diffs for later inspection."""
    logs_dir = REPO_ROOT / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / "codex_ci.log"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("\n=== CODEx Interaction ===\n")
            handle.write(f"Kind: {kind}\n")
            handle.write("--- Prompt ---\n")
            handle.write(prompt.strip() + "\n")
            handle.write("--- Response ---\n")
            handle.write(response.strip() + "\n")
    except OSError:
        pass


def load_env_file(path: str) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file."""
    env: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if value and value[0] == value[-1] and value[0] in {"'", '"'}:
                    value = value[1:-1]
                env[key] = value
    except FileNotFoundError:
        return {}
    return env


def load_env_settings(env_path: str) -> None:
    """Populate useful environment variables from a dotenv file when not already set."""
    expanded = os.path.expanduser(env_path)
    env_values = load_env_file(expanded)
    if "OPENAI_MODEL" not in os.environ:
        model = env_values.get("OPENAI_MODEL")
        if model:
            os.environ["OPENAI_MODEL"] = model
            print(f"[info] Loaded OPENAI_MODEL from {expanded}")


def detect_missing_symbol_error(log_excerpt: str) -> Optional[str]:
    """Identify ImportErrors caused by undefined symbols in first-party modules."""
    match = IMPORT_ERROR_PATTERN.search(log_excerpt)
    if not match:
        return None
    symbol, module_path = match.groups()
    if not module_path.startswith("src."):
        return None
    module_parts = module_path.split(".")
    module_relative = Path(*module_parts)
    candidate_files = [
        module_relative.with_suffix(".py"),
        module_relative / "__init__.py",
    ]
    target_file: Optional[Path] = None
    contents = ""
    for relative in candidate_files:
        candidate = REPO_ROOT / relative
        if candidate.exists() and candidate.is_file():
            target_file = candidate
            try:
                contents = candidate.read_text(encoding="utf-8")
            except OSError:
                contents = ""
            break
    if target_file is None:
        return None
    symbol_regex = re.compile(rf"\b(def|class)\s+{re.escape(symbol)}\b")
    if symbol_regex.search(contents) or re.search(rf"\b{re.escape(symbol)}\b", contents):
        return None
    relative_display = target_file.relative_to(REPO_ROOT)
    return (
        f"ImportError detected: `{symbol}` is missing from `{module_path}` "
        f"(checked `{relative_display}`)."
    )


def detect_attribute_error(log_excerpt: str) -> Optional[str]:
    """Identify attribute access errors likely caused by missing members."""
    match = ATTRIBUTE_ERROR_PATTERN.search(log_excerpt)
    if not match:
        return None
    attribute = match.group(1)
    # Look for the most recent stack frame referencing the repository.
    frame_match = re.findall(r'File "([^"]+)", line \d+, in [^\n]+', log_excerpt)
    candidate_file: Optional[Path] = None
    for frame in reversed(frame_match):
        frame_path = Path(frame)
        try:
            resolved = frame_path.resolve()
        except OSError:
            continue
        try:
            relative = resolved.relative_to(REPO_ROOT)
        except ValueError:
            continue
        candidate_file = relative
        break
    if candidate_file is None:
        return None
    return (
        f"AttributeError detected: missing attribute `{attribute}` in `{candidate_file}`.\n"
        "Review the failing attribute manually before retrying ci.py."
    )


def summarize_failure(log_excerpt: str) -> tuple[str, list[str]]:
    """
    Produce a short failure summary and list of implicated files.

    Currently recognises pyright output (reporting type errors with absolute paths).
    """
    lines = log_excerpt.splitlines()
    pyright_matches: list[tuple[str, str]] = []
    for line in lines:
        if "pyright" in line and ":" in line:
            continue
        match = re.search(r"/Users/[^:]+/(.+?):(\d+)", line)
        if match:
            relative_path, lineno = match.groups()
            pyright_matches.append((relative_path, lineno))
    if pyright_matches:
        unique_files: dict[str, str] = {}
        for rel_path, lineno in pyright_matches:
            unique_files.setdefault(rel_path, lineno)
        summary_lines = [
            "pyright reported type errors:",
            *[
                f"- {path}:{lineno}"
                for path, lineno in unique_files.items()
            ],
        ]
        return "\n".join(summary_lines), list(unique_files.keys())
    return "", []


def invoke_codex(
    prompt: str,
    *,
    model: str,
    description: str,
    reasoning_effort: Optional[str],
) -> str:
    """Run the Codex CLI non-interactively with the given prompt."""
    cmd = ["codex", "exec", "--model", model]
    if reasoning_effort:
        cmd.extend(["-c", f"model_reasoning_effort={reasoning_effort}"])
    cmd.append("-")
    effort_display = reasoning_effort or "default"
    print(
        f"[codex] Requesting {description} via Codex CLI "
        f"(model={model}, reasoning_effort={effort_display})..."
    )
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _feed() -> None:
        try:
            if process.stdin:
                process.stdin.write(prompt)
                process.stdin.close()
        except BrokenPipeError:
            pass

    def _stream(pipe, collector: list[str], target) -> None:
        try:
            for line in iter(pipe.readline, ""):
                collector.append(line)
                target.write(line)
                target.flush()
        finally:
            pipe.close()

    feeder = threading.Thread(target=_feed, daemon=True)
    feeder.start()

    threads = []
    if process.stdout:
        threads.append(
            threading.Thread(
                target=_stream, args=(process.stdout, stdout_lines, sys.stdout), daemon=True
            )
        )
        threads[-1].start()
    if process.stderr:
        threads.append(
            threading.Thread(
                target=_stream, args=(process.stderr, stderr_lines, sys.stderr), daemon=True
            )
        )
        threads[-1].start()

    feeder.join()
    for thread in threads:
        thread.join()

    returncode = process.wait()
    stdout = "".join(stdout_lines).strip()
    stderr = "".join(stderr_lines).strip()

    log_codex_interaction(description, prompt, stdout or stderr)

    if returncode != 0:
        error_details = stderr or stdout
        raise CodexCliError.exit_status(returncode=returncode, output=error_details)

    if stdout.startswith("assistant:"):
        stdout = stdout.partition("\n")[2].strip()
    if not stdout:
        return stderr
    return stdout


def request_codex_patch(
    *,
    model: str,
    reasoning_effort: Optional[str],
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
    """Call the Codex CLI to request a patch for the current failure."""
    effort_display = reasoning_effort or "default"
    prompt = textwrap.dedent(
        f"""\
        Model configuration:
        - Model: {model}
        - Reasoning effort: {effort_display}

        {REPO_CONTEXT}

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


def extract_unified_diff(response_text: str) -> Optional[str]:
    """Extract the unified diff from the Codex reply."""
    if not response_text:
        return None
    if response_text.strip().upper() == "NOOP":
        return None
    code_blocks = re.findall(r"```(?:diff)?\s*(.*?)```", response_text, flags=re.DOTALL)
    if code_blocks:
        # Return the first block that looks like a diff.
        for block in code_blocks:
            text = block.strip()
            if text.startswith(("diff", "---", "Index: ", "From ")):
                return text
        return code_blocks[0].strip()
    return response_text


def has_unified_diff_header(diff_text: str) -> bool:
    """Detect whether the diff includes standard headers."""
    return bool(re.search(r"^(diff --git|--- |\+\+\+ )", diff_text, re.MULTILINE))


def truncate_error(error: Optional[str], limit: int = 2000) -> str:
    """Truncate long error messages for prompt inclusion."""
    if not error:
        return "(none)"
    text = error.strip()
    if len(text) > limit:
        return text[:limit] + "...(truncated)"
    return text


def patch_looks_risky(patch_text: str, *, max_lines: int) -> tuple[bool, Optional[str]]:
    """Heuristic checks for risky patches."""
    if not patch_text:
        msg = "Patch content was empty."
        print(f"[guard] {msg}", file=sys.stderr)
        return True, msg
    changed_lines = sum(1 for line in patch_text.splitlines() if line.startswith(("+", "-")))
    if changed_lines > max_lines:
        msg = f"Patch has {changed_lines} changed lines which exceeds the limit of {max_lines}."
        print(f"[guard] {msg}", file=sys.stderr)
        return True, msg
    for line in patch_text.splitlines():
        if line.startswith("diff --git"):
            parts = line.split()
            if len(parts) >= 4:
                a_path = parts[2][2:]
                b_path = parts[3][2:]
                if a_path.startswith(PROTECTED_PATH_PREFIXES) or b_path.startswith(PROTECTED_PATH_PREFIXES):
                    offending = a_path if a_path.startswith(PROTECTED_PATH_PREFIXES) else b_path
                    msg = f"Patch attempted to modify protected path `{offending}`."
                    print(f"[guard] {msg}", file=sys.stderr)
                    return True, msg
    for pattern in RISKY_PATTERNS:
        if pattern.search(patch_text):
            msg = f"Patch matched risky pattern: {pattern.pattern}"
            print(f"[guard] {msg}", file=sys.stderr)
            return True, msg
    return False, None


def prompt_patch_decision(attempt: int, *, mode: str) -> str:
    """Determine whether to apply a generated patch based on approval mode."""
    if mode == "auto":
        print(f"[info] Auto-approving patch attempt {attempt} (approval mode=auto).")
        return "apply"
    while True:
        try:
            response = input(
                f"[prompt] Apply patch attempt {attempt}? [y]es/[n]o/[q]uit: "
            ).strip().lower()
        except EOFError:
            response = "q"
        if response in {"y", "yes"}:
            return "apply"
        if response in {"n", "no"}:
            return "skip"
        if response in {"q", "quit"}:
            return "quit"
        print("Please respond with 'y', 'n', or 'q'.")


class PatchApplyError(CiError):
    """Raised when a Codex-suggested patch cannot be applied safely."""

    default_message = "Patch application failed"

    def __init__(self, *, detail: str, retryable: bool):
        super().__init__(detail=detail)
        self.retryable = retryable

    @staticmethod
    def _normalize_output(output: Optional[str]) -> str:
        stripped = (output or "").strip()
        return stripped or "(no output)"

    @classmethod
    def git_apply_failed(cls, *, output: Optional[str]) -> "PatchApplyError":
        normalized = cls._normalize_output(output)
        detail = f"`git apply` failed after successful dry run ({normalized})"
        return cls(detail=detail, retryable=True)

    @classmethod
    def preflight_failed(
        cls, *, check_output: Optional[str], dry_output: Optional[str]
    ) -> "PatchApplyError":
        segments: list[str] = []
        normalized_check = cls._normalize_output(check_output)
        if normalized_check != "(no output)":
            segments.append(normalized_check)
        normalized_dry = cls._normalize_output(dry_output)
        if normalized_dry != "(no output)":
            segments.append(normalized_dry)
        combined = "\n".join(segments) if segments else "(no output)"
        detail = f"pre-flight checks rejected the patch ({combined})"
        return cls(detail=detail, retryable=True)

    @classmethod
    def patch_exit(
        cls, *, returncode: int, output: Optional[str]
    ) -> "PatchApplyError":
        normalized = cls._normalize_output(output)
        detail = f"`patch` exited with status {returncode} after dry run ({normalized})"
        return cls(detail=detail, retryable=True)


@dataclass
class CoverageDeficit:
    path: str
    coverage: float


@dataclass
class CoverageCheckResult:
    table_text: str
    deficits: list[CoverageDeficit]
    threshold: float


def extract_coverage_deficits(
    output: str, *, threshold: float = COVERAGE_THRESHOLD
) -> Optional[CoverageCheckResult]:
    """Parse pytest coverage output and report files below the threshold."""
    if not output:
        return None
    lines = output.splitlines()
    header_index: Optional[int] = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("Name") and "Cover" in stripped:
            header_index = idx
    if header_index is None:
        return None

    table_lines: list[str] = [lines[header_index]]
    for line in lines[header_index + 1 :]:
        table_lines.append(line)
        if not line.strip():
            break

    if len(table_lines) <= 1:
        return None

    deficits: list[CoverageDeficit] = []
    for entry in table_lines[2:]:
        stripped = entry.strip()
        if not stripped or stripped.startswith("-"):
            continue
        tokens = entry.split()
        if len(tokens) < 4:
            continue
        cover_token = tokens[-1]
        if not cover_token.endswith("%"):
            continue
        try:
            coverage = float(cover_token[:-1])
        except ValueError:
            continue
        path_token = " ".join(tokens[:-3]).strip()
        if not path_token or path_token.upper() == "TOTAL":
            continue
        if coverage < threshold:
            deficits.append(CoverageDeficit(path=path_token, coverage=coverage))

    if not deficits:
        return None

    table_text = "\n".join(table_lines).strip()
    return CoverageCheckResult(
        table_text=table_text, deficits=deficits, threshold=threshold
    )


def augment_patch_error(error: Optional[str], attempt: int) -> Optional[str]:
    """Ensure Codex is reminded to send full diffs after repeated failures."""
    if attempt <= 1:
        return error
    unified_hint = (
        "Repeated patch failures: respond with a complete unified diff for each file, "
        "starting with `diff --git` and including matching `---`/`+++` headers."
    )
    if not error:
        return unified_hint
    lowered = error.lower()
    if "diff --git" in lowered or "unified diff" in lowered:
        return error
    return f"{error} {unified_hint}"


def apply_patch(patch_text: str) -> None:
    """Apply a unified diff using patch -p1."""
    print("[info] Applying patch from Codex...")
    if not patch_text.endswith("\n"):
        patch_text += "\n"
    git_check = subprocess.run(
        ["git", "apply", "--check", "--whitespace=nowarn"],
        input=patch_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if git_check.returncode == 0:
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
        return

    # If the patch is already present, git apply --check --reverse will succeed.
    git_reverse_check = subprocess.run(
        ["git", "apply", "--check", "--reverse", "--whitespace=nowarn"],
        input=patch_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if git_reverse_check.returncode == 0:
        print("[info] Patch already applied according to `git apply`; skipping.")
        return

    env = dict(os.environ)
    env.setdefault("PATCH_CREATE_BACKUP", "no")

    dry_run_cmd = ["patch", "--batch", "--forward", "--reject-file=-", "-p1", "--dry-run"]
    dry_run = subprocess.run(
        dry_run_cmd,
        input=patch_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if dry_run.returncode != 0:
        check_output = (git_check.stdout or "") + (git_check.stderr or "")
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
        raise PatchApplyError.patch_exit(
            returncode=actual.returncode, output=output
        )
    if actual.stdout:
        print(actual.stdout.rstrip())


def request_commit_message(
    *,
    model: str,
    reasoning_effort: Optional[str],
    staged_diff: str,
    extra_context: str,
    detailed: bool = False,
) -> tuple[str, list[str]]:
    """Ask Codex CLI for a commit message."""
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
    body_lines: list[str],
    *,
    push: bool,
) -> None:
    """Create a commit (and optionally push it)."""
    print("[info] Creating commit...")
    commit_args = ["git", "commit", "-m", summary]
    body_text = "\n".join(body_lines).strip()
    if body_text:
        commit_args.extend(["-m", body_text])
    try:
        run_command(commit_args, check=True, live=True)
    except subprocess.CalledProcessError as exc:
        raise GitCommandAbort.commit_failed(exc) from exc

    if not push:
        return
    remote = os.environ.get("GIT_REMOTE", "origin")
    branch_result = run_command(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
    )
    branch = branch_result.stdout.strip()
    print(f"[info] Pushing to {remote}/{branch}...")
    try:
        run_command(["git", "push", remote, branch], check=True, live=True)
    except subprocess.CalledProcessError as exc:
        raise GitCommandAbort.push_failed(exc) from exc


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
            "Reasoning effort hint for Codex "
            f"(default: {DEFAULT_REASONING_EFFORT})"
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
    return parser.parse_args(argv)


def ensure_on_branch() -> None:
    """Exit early if we are in a detached HEAD state."""
    result = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    branch = result.stdout.strip()
    if branch == "HEAD":
        raise RepositoryStateAbort.detached_head()


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    ensure_on_branch()

    load_env_settings(args.env_file)
    model_name = args.model or os.environ.get("OPENAI_MODEL") or REQUIRED_MODEL
    if model_name != REQUIRED_MODEL:
        raise ModelSelectionAbort.unsupported_model(
            received=model_name, required=REQUIRED_MODEL
        )
    env_reasoning = os.environ.get("OPENAI_REASONING_EFFORT")
    reasoning_effort = (
        args.reasoning_effort
        or (env_reasoning.lower() if env_reasoning else None)
        or DEFAULT_REASONING_EFFORT
    )
    if reasoning_effort not in REASONING_EFFORT_CHOICES:
        raise ReasoningEffortAbort.unsupported_choice(
            received=reasoning_effort, allowed=REASONING_EFFORT_CHOICES
        )
    os.environ["OPENAI_MODEL"] = model_name
    os.environ["OPENAI_REASONING_EFFORT"] = reasoning_effort

    command_tokens = shlex.split(args.command)
    patch_approval_mode = args.patch_approval_mode
    command_basename = Path(command_tokens[0]).name if command_tokens else ""
    automation_mode = command_basename == "ci.sh"
    command_env: dict[str, str] = {}
    if automation_mode:
        command_env["CI_AUTOMATION"] = "1"
    auto_stage_enabled = args.auto_stage or automation_mode
    commit_message_enabled = args.commit_message or automation_mode
    auto_push_enabled = automation_mode

    if args.dry_run:
        print("[info] Dry run: executing CI command once without invoking Codex.")
        result = run_command(command_tokens, live=True, env=command_env)
        return result.returncode

    seen_patches: set[str] = set()

    try:
        for iteration in range(1, args.max_iterations + 1):
            print(f"[loop] Iteration {iteration} — running `{args.command}`")
            result = run_command(command_tokens, live=True, env=command_env)

            failure_summary = ""
            implicated_files: list[str] = []
            focused_diff = ""

            coverage_report = (
                extract_coverage_deficits(result.combined_output)
                if result.ok
                else None
            )

            if result.ok and coverage_report is None:
                print(f"[loop] CI command succeeded on iteration {iteration}.")
                break

            if coverage_report is not None:
                deficit_summary = ", ".join(
                    f"{item.path} ({item.coverage:.1f}%)"
                    for item in coverage_report.deficits
                )
                print(
                    "[coverage] Coverage below "
                    f"{coverage_report.threshold:.0f}% detected for: {deficit_summary}"
                )
                print("[loop] Consulting Codex for additional tests to lift coverage.")
                coverage_lines = [
                    f"- {item.path}: {item.coverage:.1f}%"
                    for item in coverage_report.deficits
                ]
                coverage_header = (
                    f"Coverage deficits detected (threshold {coverage_report.threshold:.0f}%):"
                )
                coverage_intro = (
                    "Coverage guard triggered: add or expand tests so each listed module "
                    f"clears {coverage_report.threshold:.0f}% line coverage."
                )
                failure_summary = "\n".join([
                    coverage_intro,
                    *coverage_lines,
                ])
                implicated_files = [item.path for item in coverage_report.deficits]
                log_excerpt = "\n".join(
                    [
                        coverage_intro,
                        "",
                        coverage_header,
                        *coverage_lines,
                        "",
                        coverage_report.table_text,
                    ]
                )
            else:
                log_excerpt = tail_text(result.combined_output, args.log_tail)
                failure_summary, implicated_files = summarize_failure(log_excerpt)
                missing_symbol_hint = detect_missing_symbol_error(log_excerpt)
                if missing_symbol_hint:
                    print(f"[guard] {missing_symbol_hint}", file=sys.stderr)
                    print(
                        "[guard] Resolve the missing symbol or adjust the import before rerunning ci.py.",
                        file=sys.stderr,
                    )
                    return 1
                attribute_error_hint = detect_attribute_error(log_excerpt)
                if attribute_error_hint:
                    print(f"[guard] {attribute_error_hint}", file=sys.stderr)
                    return 1
                print(f"[loop] CI failed with exit code {result.returncode}. Consulting Codex...")

            git_status = gather_git_status()
            git_diff = gather_git_diff(staged=False)
            if implicated_files:
                focused_blocks = []
                for rel_path in implicated_files:
                    diff_block = gather_file_diff(rel_path)
                    if diff_block:
                        focused_blocks.append(diff_block)
                focused_diff = "\n\n".join(focused_blocks)

            patch_error: Optional[str] = None
            patch_attempt = 1
            max_attempts = args.patch_retries + 1
            extra_retry_budget = 3

            while True:
                if patch_attempt > max_attempts:
                    raise PatchLifecycleAbort.attempts_exhausted()

                print(f"[codex] Requesting patch attempt {patch_attempt}...")
                prompt_patch_error = augment_patch_error(patch_error, patch_attempt)
                codex_reply = request_codex_patch(
                    model=model_name,
                    reasoning_effort=reasoning_effort,
                    command=args.command,
                    log_excerpt=log_excerpt,
                    summary=failure_summary,
                    focused_diff=focused_diff,
                    git_diff=git_diff,
                    git_status=git_status,
                    iteration=iteration,
                    patch_error=prompt_patch_error,
                    attempt=patch_attempt,
                )

                diff_text = extract_unified_diff(codex_reply or "")
                if not diff_text:
                    raise PatchLifecycleAbort.missing_patch()
                if diff_text in seen_patches:
                    patch_error = "Duplicate patch received; provide an alternative diff."
                    print("[warn] Duplicate patch received from Codex; requesting a new patch.")
                    patch_attempt += 1
                    continue
                print(f"[codex] Patch attempt {patch_attempt} diff:")
                print(diff_text)
                print(f"[codex] Diff length: {len(diff_text.splitlines())} lines")
                seen_patches.add(diff_text)
                if not has_unified_diff_header(diff_text):
                    patch_error = "Patch missing unified diff headers (diff --git/---/+++ lines)."
                    print("[warn] Patch lacked diff headers; requesting a new patch.")
                    patch_attempt += 1
                    continue
                is_risky, reason = patch_looks_risky(diff_text, max_lines=args.max_patch_lines)
                if is_risky:
                    patch_error = reason or "Patch failed safety checks."
                    print("[warn] Patch failed safety checks; requesting a new patch.")
                    patch_attempt += 1
                    continue

                decision = prompt_patch_decision(patch_attempt, mode=patch_approval_mode)
                if decision == "skip":
                    patch_error = "User declined to apply the patch."
                    print("[info] Patch skipped by user; requesting a new patch.")
                    patch_attempt += 1
                    continue
                if decision == "quit":
                    raise PatchLifecycleAbort.user_declined()

                try:
                    apply_patch(diff_text)
                except PatchApplyError as exc:
                    patch_error = str(exc)
                    print(f"[warn] Patch attempt {patch_attempt} failed to apply: {exc}")
                    if exc.retryable and patch_attempt >= max_attempts:
                        if extra_retry_budget > 0:
                            extra_retry_budget -= 1
                            max_attempts += 1
                        else:
                            raise PatchLifecycleAbort.retries_exhausted()
                    elif not exc.retryable and patch_attempt >= max_attempts:
                        raise PatchLifecycleAbort.retries_exhausted()
                    git_status = gather_git_status()
                    git_diff = gather_git_diff(staged=False)
                    patch_attempt += 1
                    continue
                except RuntimeError as exc:
                    patch_error = str(exc)
                    print(f"[warn] Patch attempt {patch_attempt} failed to apply: {exc}")
                    if patch_attempt >= max_attempts:
                        raise PatchLifecycleAbort.retries_exhausted()
                    # Refresh git status/diff in case the patch partially applied.
                    git_status = gather_git_status()
                    git_diff = gather_git_diff(staged=False)
                    patch_attempt += 1
                    continue

                post_status = gather_git_status()
                if post_status:
                    print("[info] git status after patch:")
                    print(post_status)
                else:
                    print("[info] Working tree is clean after applying patch.")
                break
        else:
            print(
                f"[error] Reached maximum iterations ({args.max_iterations}) without success.",
                file=sys.stderr,
            )
            return 1
    except KeyboardInterrupt:
        print("\n[info] Received Ctrl-C. Aborting ci.py cleanly.")
        return 130

    unstaged_diff = gather_git_diff(staged=False)
    staged_diff = gather_git_diff(staged=True)
    if not unstaged_diff and not staged_diff:
        print("[info] Working tree clean. Nothing to stage or commit.")
        return 0

    if auto_stage_enabled:
        print("[info] Staging all changes (`git add -A`).")
        run_command(["git", "add", "-A"], check=True)
        staged_diff = gather_git_diff(staged=True)

    if not staged_diff:
        print(
            "[warn] No staged changes detected. Stage files before requesting a commit message.",
            file=sys.stderr,
        )
        return 0

    commit_summary: Optional[str] = None
    commit_body_lines: list[str] = []
    if commit_message_enabled:
        commit_summary, commit_body_lines = request_commit_message(
            model=model_name,
            reasoning_effort=reasoning_effort,
            staged_diff=staged_diff,
            extra_context=args.commit_extra_context,
            detailed=auto_push_enabled,
        )
        preview_lines: list[str] = [commit_summary]
        if commit_body_lines:
            preview_lines.append("")
            preview_lines.extend(commit_body_lines)
        print("[info] Suggested commit message:")
        for line in preview_lines:
            if line:
                print(f"    {line}")
            else:
                print()

    if auto_push_enabled:
        if commit_summary is None:
            commit_summary = "Automated commit"
            commit_body_lines = []
        commit_and_push(commit_summary, commit_body_lines, push=True)
    elif commit_summary is not None:
        print("[info] Commit message ready; run `git commit` manually if desired.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
