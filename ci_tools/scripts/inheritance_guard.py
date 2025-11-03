#!/usr/bin/env python3
"""Fail the build when class inheritance depth exceeds configured limits.

Detects deep inheritance chains that indicate mixin complexity and hard-to-reason-about
hierarchies. Prefer composition over deep inheritance.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from ci_tools.scripts.guard_common import (
    GuardRunner,
    make_relative_path,
)


def extract_base_names(node: ast.ClassDef) -> List[str]:
    """Extract base class names from a ClassDef node."""
    base_names: List[str] = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            base_names.append(base.id)
        elif isinstance(base, ast.Attribute):
            # Handle cases like module.ClassName
            parts: List[str] = []
            current = base
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            base_names.append(".".join(reversed(parts)))
    return base_names


def build_class_hierarchy(tree: ast.AST) -> Dict[str, List[str]]:
    """Build a map of class_name -> list of base_class_names."""
    hierarchy: Dict[str, List[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            hierarchy[node.name] = extract_base_names(node)
    return hierarchy


def calculate_depth(
    class_name: str,
    hierarchy: Dict[str, List[str]],
    visited: Optional[Set[str]] = None,
) -> int:
    """Calculate the maximum inheritance depth for a class.

    Returns 0 for classes with no bases, 1 for direct inheritance, etc.
    """
    if visited is None:
        visited = set()

    # Cycle detection
    if class_name in visited:
        return 0
    visited.add(class_name)

    # No inheritance info (external class or no bases)
    if class_name not in hierarchy:
        return 0

    bases = hierarchy[class_name]
    if not bases:
        return 0

    # Recursively calculate depth for each base
    max_base_depth = 0
    has_real_bases = False
    for base in bases:
        # Skip common base classes that don't count as "real" inheritance
        if base in ("object", "Protocol", "ABC"):
            continue
        has_real_bases = True
        base_depth = calculate_depth(base, hierarchy, visited.copy())
        max_base_depth = max(max_base_depth, base_depth)

    # Only count depth if there were non-skipped bases
    return max_base_depth + 1 if has_real_bases else 0


class InheritanceGuard(GuardRunner):
    """Guard that detects excessive inheritance depth."""

    def __init__(self):
        super().__init__(
            name="inheritance_guard",
            description="Detect classes with excessive inheritance depth.",
            default_root=Path("src"),
        )

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        """Add inheritance-specific arguments."""
        parser.add_argument(
            "--max-depth",
            type=int,
            default=2,
            help="Maximum allowed inheritance depth (default: 2, meaning class → parent → grandparent).",
        )

    def scan_file(self, path: Path, args: argparse.Namespace) -> List[str]:
        """Scan a file for inheritance depth violations."""
        source = path.read_text()
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            raise RuntimeError(
                f"failed to parse Python source: {path} ({exc})"
            ) from exc

        hierarchy = build_class_hierarchy(tree)
        violations: List[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                depth = calculate_depth(node.name, hierarchy)
                if depth > args.max_depth:
                    base_names = extract_base_names(node)
                    relative = make_relative_path(path, self.repo_root)
                    bases_str = ", ".join(base_names) if base_names else "(none)"
                    violations.append(
                        f"{relative}:{node.lineno} class {node.name} has inheritance "
                        f"depth {depth} (limit {args.max_depth}) - bases: {bases_str}"
                    )

        return violations

    def get_violations_header(self, args: argparse.Namespace) -> str:
        """Get the header for violations report."""
        return (
            "Deep inheritance detected. Refactor the following classes "
            f"to stay within depth {args.max_depth} (prefer composition over inheritance):"
        )

    def get_violations_footer(self, args: argparse.Namespace) -> Optional[str]:
        """Get the footer tip for violations report."""
        return (
            "Tip: Replace mixin inheritance with service objects injected via __init__"
        )


def main(argv: Optional[Iterable[str]] = None) -> int:
    """Main entry point for inheritance_guard."""
    guard = InheritanceGuard()
    return guard.run(argv)


if __name__ == "__main__":
    sys.exit(main())
