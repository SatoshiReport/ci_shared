#!/usr/bin/env python3
"""Fail the build when classes instantiate too many dependencies.

High dependency counts in __init__ or __post_init__ indicate orchestrators
handling multiple concerns. Consider dependency injection or extracting coordinators.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Iterable, List, Optional

from ci_tools.scripts.guard_common import (
    GuardRunner,
    make_relative_path,
)

SKIPPED_CONSTRUCTOR_NAMES = {
    "Path",
    "Optional",
    "List",
    "Dict",
    "Set",
    "Tuple",
    "Any",
    "Union",
}


def _callee_name(node: ast.Call) -> Optional[str]:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _is_constructor_name(name: str) -> bool:
    if not name:
        return False
    return name[0].isupper() and name not in SKIPPED_CONSTRUCTOR_NAMES


def count_instantiations(func_node: ast.FunctionDef) -> tuple[int, List[str]]:
    """Count object instantiations (calls that look like constructors)."""
    count = 0
    instantiated_classes: List[str] = []
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        callee_name = _callee_name(node)
        if callee_name and _is_constructor_name(callee_name):
            count += 1
            instantiated_classes.append(callee_name)
    return count, instantiated_classes


class DependencyGuard(GuardRunner):
    """Guard that detects excessive dependency instantiation."""

    def __init__(self):
        super().__init__(
            name="dependency_guard",
            description="Detect classes with excessive dependency instantiation.",
            default_root=Path("src"),
        )

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        """Add dependency-specific arguments."""
        parser.add_argument(
            "--max-instantiations",
            type=int,
            default=8,
            help="Maximum allowed object instantiations in __init__/__post_init__ (default: 8).",
        )

    def _check_class_init(
        self, node: ast.ClassDef, path: Path, max_inst: int
    ) -> Optional[str]:
        """Check __init__/__post_init__ for excessive instantiations."""
        for item in node.body:
            if not isinstance(item, ast.FunctionDef) or item.name not in (
                "__init__",
                "__post_init__",
            ):
                continue
            count, instantiated = count_instantiations(item)
            if count > max_inst:
                relative = make_relative_path(path, self.repo_root)
                classes_str = ", ".join(instantiated[:5])
                if len(instantiated) > 5:
                    classes_str += f", ... ({len(instantiated) - 5} more)"
                return (
                    f"{relative}:{node.lineno} class {node.name} instantiates {count} dependencies "
                    f"(limit {max_inst}) - [{classes_str}]"
                )
        return None

    def scan_file(self, path: Path, args: argparse.Namespace) -> List[str]:
        """Scan a file for dependency instantiation violations."""
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
                if violation := self._check_class_init(
                    node, path, args.max_instantiations
                ):
                    violations.append(violation)
        return violations

    def get_violations_header(self, args: argparse.Namespace) -> str:
        """Get the header for violations report."""
        return (
            "Classes with too many dependency instantiations detected. "
            "Consider dependency injection or extracting coordinators:"
        )

    def get_violations_footer(self, args: argparse.Namespace) -> Optional[str]:
        """Get the footer tip for violations report."""
        return "Tip: Pass dependencies via __init__ parameters instead of instantiating them internally"


def main(argv: Optional[Iterable[str]] = None) -> int:
    """Main entry point for dependency_guard."""
    guard = DependencyGuard()
    return guard.run(argv)


if __name__ == "__main__":
    sys.exit(main())
