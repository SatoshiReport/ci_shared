"""Fail the build when functions exceed configured line limits."""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from ci_tools.scripts.guard_common import (
    GuardRunner,
    make_relative_path,
)


def count_function_lines(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Count lines spanned by a function definition."""
    if not hasattr(node, "end_lineno") or node.end_lineno is None:
        return 0
    return node.end_lineno - node.lineno + 1


class FunctionSizeGuard(GuardRunner):
    """Guard that detects oversized functions."""

    def __init__(self):
        super().__init__(
            name="function_size_guard",
            description="Detect oversized functions that should be refactored.",
            default_root=Path("src"),
        )

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        """Add function-specific arguments."""
        parser.add_argument(
            "--max-function-lines",
            type=int,
            default=80,
            help="Maximum allowed lines per function (default: 80).",
        )

    def scan_file(self, path: Path, args: argparse.Namespace) -> List[str]:
        """Scan a file for function size violations."""
        try:
            content = path.read_text()
            tree = ast.parse(content, filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            print(f"{self.name}: failed to parse {path}: {exc}", file=sys.stderr)
            return []

        violations: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                line_count = count_function_lines(node)
                if line_count > args.max_function_lines:
                    relative = make_relative_path(path, self.repo_root)
                    violations.append(
                        f"{relative}::{node.name} (line {node.lineno}) contains {line_count} lines "
                        f"(limit {args.max_function_lines})"
                    )

        return violations

    def get_violations_header(self, args: argparse.Namespace) -> str:
        """Get the header for violations report."""
        return (
            f"Oversized functions detected. Refactor functions to stay within "
            f"{args.max_function_lines} lines:"
        )


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments (backward compatibility wrapper)."""
    guard = FunctionSizeGuard()
    return guard.parse_args(argv)


def scan_file(path: Path, limit: int) -> List[Tuple[Path, str, int, int]]:
    """Scan a file for function size violations (backward compatibility wrapper)."""
    try:
        content = path.read_text()
        tree = ast.parse(content, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []
    violations: List[Tuple[Path, str, int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            line_count = count_function_lines(node)
            if line_count > limit:
                violations.append((path, node.name, node.lineno, line_count))
    return violations


def main(argv: Optional[Iterable[str]] = None) -> int:
    """Main entry point for function_size_guard."""
    guard = FunctionSizeGuard()
    return guard.run(argv)


if __name__ == "__main__":
    sys.exit(main())
