"""Fail the build when Python modules exceed configured line limits."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Optional

from ci_tools.scripts.guard_common import (
    GuardRunner,
    make_relative_path,
)


def count_lines(path: Path) -> int:
    """Count non-empty, non-comment-only lines in a Python module."""
    lines = path.read_text().splitlines()
    significant_lines = 0
    for line in lines:
        stripped = line.strip()
        # Count non-empty lines that aren't just comments
        if stripped and not stripped.startswith("#"):
            significant_lines += 1
    return significant_lines


class ModuleGuard(GuardRunner):
    """Guard that detects oversized Python modules."""

    def __init__(self):
        super().__init__(
            name="module_guard",
            description="Detect oversized Python modules that need refactoring.",
            default_root=Path("src"),
        )

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        """Add module-specific arguments."""
        parser.add_argument(
            "--max-module-lines",
            type=int,
            default=600,
            help="Maximum allowed number of lines per module (file).",
        )

    def scan_file(self, path: Path, args: argparse.Namespace) -> List[str]:
        """Scan a file for module size violations."""
        try:
            line_count = count_lines(path)
        except (OSError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"failed to read Python source: {path} ({exc})") from exc

        if line_count > args.max_module_lines:
            relative = make_relative_path(path, self.repo_root)
            return [
                f"{relative} contains {line_count} lines "
                f"(limit {args.max_module_lines})"
            ]
        return []

    def get_violations_header(self, args: argparse.Namespace) -> str:
        """Get the header for violations report."""
        return (
            "Oversized modules detected. Refactor the following files "
            f"to stay within {args.max_module_lines} lines:"
        )


def main(argv: Optional[Iterable[str]] = None) -> int:
    """Main entry point for module_guard."""
    guard = ModuleGuard()
    return guard.run(argv)


if __name__ == "__main__":
    sys.exit(main())
