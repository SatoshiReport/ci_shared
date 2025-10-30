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


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect classes with excessive method counts (multi-concern indicator)."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("src"),
        help="Directory to scan for Python modules (defaults to ./src).",
    )
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
    parser.add_argument(
        "--exclude",
        action="append",
        type=Path,
        default=[],
        help="Path prefix to exclude from the scan (may be passed multiple times).",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def iter_python_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    for candidate in root.rglob("*.py"):
        yield candidate


def is_excluded(path: Path, exclusions: List[Path]) -> bool:
    for excluded in exclusions:
        try:
            if path.is_relative_to(excluded):
                return True
        except ValueError:
            continue
    return False


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

        # Skip dunder methods
        if item.name.startswith("__") and item.name.endswith("__"):
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


def scan_file(
    path: Path, max_public: int, max_total: int
) -> List[Tuple[Path, str, int, int, int]]:
    """Return list of (path, class_name, line_number, public_count, total_count) for violations."""
    source = path.read_text()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise RuntimeError(f"failed to parse Python source: {path} ({exc})") from exc

    violations: List[Tuple[Path, str, int, int, int]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            public_count, total_count = count_methods(node)
            if public_count > max_public or total_count > max_total:
                violations.append(
                    (path, node.name, node.lineno, public_count, total_count)
                )

    return violations


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    exclusions = [path.resolve() for path in args.exclude]
    repo_root = Path.cwd()

    violations: List[str] = []
    try:
        file_iter = list(iter_python_files(root))
    except OSError as exc:
        print(
            f"method_count_guard: failed to traverse {root}: {exc}",
            file=sys.stderr,
        )
        return 1

    for file_path in file_iter:
        resolved = file_path.resolve()
        if is_excluded(resolved, exclusions):
            continue
        try:
            entries = scan_file(
                resolved, args.max_public_methods, args.max_total_methods
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        for entry_path, class_name, lineno, public_count, total_count in entries:
            try:
                relative = entry_path.resolve().relative_to(repo_root)
            except ValueError:
                relative = entry_path

            violation_parts: List[str] = []
            if public_count > args.max_public_methods:
                violation_parts.append(
                    f"{public_count} public methods (limit {args.max_public_methods})"
                )
            if total_count > args.max_total_methods:
                violation_parts.append(
                    f"{total_count} total methods (limit {args.max_total_methods})"
                )

            violations.append(
                f"{relative}:{lineno} class {class_name} has {', '.join(violation_parts)}"
            )

    if violations:
        header = (
            "Classes with too many methods detected (multi-concern indicator). "
            "Consider extracting service objects or using composition:"
        )
        print(header, file=sys.stderr)
        for violation in sorted(violations):
            print(f"  - {violation}", file=sys.stderr)
        print(
            "\nTip: Extract groups of related methods into separate service classes",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
