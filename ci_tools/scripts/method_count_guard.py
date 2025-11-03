#!/usr/bin/env python3
"""Fail the build when classes have too many methods.

High method counts often indicate Single Responsibility Principle violations where
a class is handling multiple concerns. Consider extracting service objects.
"""

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


def count_methods(node: ast.ClassDef) -> Tuple[int, int]:
    """Count public and total methods in a class.

    Returns:
        (public_count, total_count)

    Excludes:
        - Dunder methods (__init__, __str__, etc.)
        - Properties (@property decorated methods)
    """
    public_count = 0
    total_count = 0

    for item in node.body:
        if not isinstance(item, ast.FunctionDef):
            continue

        # Skip dunder methods and name-mangled methods
        if item.name.startswith("__"):
            continue

        # Skip properties (they're data access, not behavior)
        is_property = any(
            isinstance(dec, ast.Name) and dec.id == "property"
            for dec in item.decorator_list
        )
        if is_property:
            continue

        total_count += 1

        # Count public methods (not starting with _)
        if not item.name.startswith("_"):
            public_count += 1

    return public_count, total_count


class MethodCountGuard(GuardRunner):
    """Guard that detects classes with excessive method counts."""

    def __init__(self):
        super().__init__(
            name="method_count_guard",
            description="Detect classes with excessive method counts (multi-concern indicator).",
            default_root=Path("src"),
        )

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        """Add method-count-specific arguments."""
        parser.add_argument(
            "--max-public-methods",
            type=int,
            default=15,
            help="Maximum allowed public methods per class (default: 15).",
        )
        parser.add_argument(
            "--max-total-methods",
            type=int,
            default=25,
            help="Maximum allowed total methods (public + private) per class (default: 25).",
        )

    def _build_violation(
        self,
        path: Path,
        node: ast.ClassDef,
        pub: int,
        tot: int,
        args: argparse.Namespace,
    ) -> Optional[str]:
        """Build violation message if limits exceeded."""
        if pub <= args.max_public_methods and tot <= args.max_total_methods:
            return None
        relative = make_relative_path(path, self.repo_root)
        parts: List[str] = []
        if pub > args.max_public_methods:
            parts.append(f"{pub} public methods (limit {args.max_public_methods})")
        if tot > args.max_total_methods:
            parts.append(f"{tot} total methods (limit {args.max_total_methods})")
        return f"{relative}:{node.lineno} class {node.name} has {', '.join(parts)}"

    def scan_file(self, path: Path, args: argparse.Namespace) -> List[str]:
        """Scan a file for method count violations."""
        source = path.read_text()
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            raise RuntimeError(
                f"failed to parse Python source: {path} ({exc})"
            ) from exc
        violations: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                pub, tot = count_methods(node)
                if violation := self._build_violation(path, node, pub, tot, args):
                    violations.append(violation)
        return violations

    def get_violations_header(self, args: argparse.Namespace) -> str:
        """Get the header for violations report."""
        return (
            "Classes with too many methods detected (multi-concern indicator). "
            "Consider extracting service objects or using composition:"
        )

    def get_violations_footer(self, args: argparse.Namespace) -> Optional[str]:
        """Get the footer tip for violations report."""
        return "Tip: Extract groups of related methods into separate service classes"


def main(argv: Optional[Iterable[str]] = None) -> int:
    """Main entry point for method_count_guard."""
    guard = MethodCountGuard()
    return guard.run(argv)


if __name__ == "__main__":
    sys.exit(main())
