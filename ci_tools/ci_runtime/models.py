"""Core data models and exception types for the CI runtime."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Iterable, Optional


class CiError(RuntimeError):
    """Base class for CI automation runtime failures."""

    default_message = "CI automation failure"

    def __init__(self, *, detail: Optional[str] = None) -> None:
        self.detail = detail
        message = (
            self.default_message
            if detail is None
            else f"{self.default_message}: {detail}"
        )
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

    def __init__(self, *, detail: Optional[str] = None, code: int = 1) -> None:
        self.detail = detail
        self.exit_code = code
        message = (
            self.default_message
            if detail is None
            else f"{self.default_message}: {detail}"
        )
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
        return cls(
            detail="detached HEAD detected; checkout a branch before running ci.py"
        )


class ModelSelectionAbort(CiAbort):
    """Raised when an unsupported model is provided to the CI workflow."""

    default_message = "Unsupported model configuration"

    @classmethod
    def unsupported_model(
        cls, *, received: str, required: str
    ) -> "ModelSelectionAbort":
        return cls(detail=f"requires `{required}` but received `{received}`")


class ReasoningEffortAbort(CiAbort):
    """Raised when an unsupported reasoning effort value is supplied."""

    default_message = "Unsupported reasoning effort"

    @classmethod
    def unsupported_choice(
        cls, *, received: str, allowed: Iterable[str]
    ) -> "ReasoningEffortAbort":
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
        return cls(
            detail="Codex patches failed after exhausting retries; manual review required"
        )


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


@dataclass
class RuntimeOptions:  # pylint: disable=too-many-instance-attributes
    command_tokens: list[str]
    command_env: dict[str, str]
    patch_approval_mode: str
    automation_mode: bool
    auto_stage_enabled: bool
    commit_message_enabled: bool
    auto_push_enabled: bool
    model_name: str
    reasoning_effort: str


@dataclass
class FailureContext:
    log_excerpt: str
    summary: str
    implicated_files: list[str]
    focused_diff: str
    coverage_report: Optional["CoverageCheckResult"]


@dataclass
class PatchAttemptState:
    max_attempts: int
    patch_attempt: int = 1
    extra_retry_budget: int = 3
    last_error: Optional[str] = None

    def ensure_budget(self) -> None:
        if self.patch_attempt > self.max_attempts:
            raise PatchLifecycleAbort.attempts_exhausted()

    def record_failure(self, message: str, *, retryable: bool) -> None:
        self.last_error = message
        if self.patch_attempt >= self.max_attempts:
            if retryable and self.extra_retry_budget > 0:
                self.extra_retry_budget -= 1
                self.max_attempts += 1
            else:
                raise PatchLifecycleAbort.retries_exhausted()
        self.patch_attempt += 1


class PatchApplyError(CiError):
    """Raised when git or patch apply steps fail."""

    default_message = "Patch application failed"

    def __init__(self, *, detail: Optional[str] = None, retryable: bool = True) -> None:
        super().__init__(detail=detail)
        self.retryable = retryable

    @classmethod
    def git_apply_failed(cls, *, output: str) -> "PatchApplyError":
        normalized = (output or "").strip() or "(no output)"
        detail = f"`git apply` failed: {normalized}"
        return cls(detail=detail, retryable=True)

    @classmethod
    def preflight_failed(
        cls, *, check_output: str, dry_output: str
    ) -> "PatchApplyError":
        detail = (
            "Patch dry-run failed.\n"
            f"git apply --check output:\n{(check_output or '').strip() or '(none)'}\n\n"
            f"patch --dry-run output:\n{(dry_output or '').strip() or '(none)'}"
        )
        return cls(detail=detail, retryable=True)

    @classmethod
    def patch_exit(cls, *, returncode: int, output: str) -> "PatchApplyError":
        normalized = (output or "").strip() or "(no output)"
        detail = f"`patch` exited with status {returncode}: {normalized}"
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


__all__ = [
    "CiError",
    "CodexCliError",
    "CommitMessageError",
    "CiAbort",
    "GitCommandAbort",
    "RepositoryStateAbort",
    "ModelSelectionAbort",
    "ReasoningEffortAbort",
    "PatchLifecycleAbort",
    "PatchApplyError",
    "CommandResult",
    "RuntimeOptions",
    "FailureContext",
    "PatchAttemptState",
    "CoverageDeficit",
    "CoverageCheckResult",
]
