"""Compatibility layer re-exporting the CI runtime helpers."""

from __future__ import annotations

from . import ci_runtime as _ci_runtime

__all__ = tuple(getattr(_ci_runtime, "__all__", ()))
for _name in __all__:
    globals()[_name] = getattr(_ci_runtime, _name)

# Explicit aliases for static type checkers
main = _ci_runtime.main
gather_git_diff = _ci_runtime.gather_git_diff
request_commit_message = _ci_runtime.request_commit_message
