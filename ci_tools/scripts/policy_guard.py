#!/usr/bin/env python3
"""Entry point that delegates to the policy checks module."""

from __future__ import annotations

import sys

from . import policy_checks as _policy_checks
from .policy_checks import *  # noqa: F401,F403

__all__ = getattr(_policy_checks, "__all__", [])


def main() -> int:  # pragma: no cover - thin wrapper
    return _policy_checks.main()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except _policy_checks.PolicyViolation as err:
        print(err, file=sys.stderr)
        sys.exit(1)
