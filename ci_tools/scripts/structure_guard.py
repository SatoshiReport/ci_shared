"""Fail the build when Python classes exceed configured line limits."""

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


def class_line_span(node: ast.ClassDef) -> Tuple[int, int]:
    start = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", None)
    if end is None:
        end = start
        for inner in ast.walk(node):
            inner_end = getattr(inner, "end_lineno", None)
            if inner_end is not None and inner_end > end:
                end = inner_end
    return start, end


class StructureGuard(GuardRunner):
    """Guard that detects oversized Python classes."""

    def __init__(self):
        super().__init__(
            name="structure_guard",
            description="Detect oversized Python classes that need refactoring.",
            default_root=Path("src"),
        )

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        """Add structure-specific arguments."""
        parser.add_argument(
            "--max-class-lines",
            type=int,
            default=100,
            help="Maximum allowed number of lines per class definition.",
        )

    def scan_file(self, path: Path, args: argparse.Namespace) -> List[str]:
        """Scan a file for class size violations."""
        source = path.read_text()
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            raise RuntimeError(
                f"failed to parse Python source: {path} ({exc})"
            ) from exc

        violations: List[str] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                start, end = class_line_span(node)
                length = end - start + 1
                if length > args.max_class_lines:
                    relative = make_relative_path(path, self.repo_root)
                    violations.append(
                        f"{relative}:{start} class {node.name} spans {length} lines "
                        f"(limit {args.max_class_lines})"
                    )
        return violations

    def get_violations_header(self, args: argparse.Namespace) -> str:
        """Get the header for violations report."""
        return (
            "Oversized classes detected. Refactor the following definitions "
            f"to stay within {args.max_class_lines} lines:"
        )


def main(argv: Optional[Iterable[str]] = None) -> int:
    """Main entry point for structure_guard."""
    guard = StructureGuard()
    return guard.run(argv)


if __name__ == "__main__":
    sys.exit(main())
