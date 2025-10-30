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
from typing import Iterable, List, Optional, Tuple


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect classes with excessive dependency instantiation."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("src"),
        help="Directory to scan for Python modules (defaults to ./src).",
    )
    parser.add_argument(
        "--max-instantiations",
        type=int,
        default=8,
        help="Maximum allowed object instantiations in __init__/__post_init__ (default: 8).",
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


def count_instantiations(func_node: ast.FunctionDef) -> Tuple[int, List[str]]:
    """Count object instantiations (calls that look like constructors).

    Returns:
        (count, list of instantiated class names)
    """
    count = 0
    instantiated_classes: List[str] = []

    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            # Check if it's a constructor call (capitalized function name)
            callee_name: Optional[str] = None

            if isinstance(node.func, ast.Name):
                # Simple call: ClassName()
                callee_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                # Attribute call: module.ClassName()
                callee_name = node.func.attr

            # Constructor heuristic: starts with uppercase letter
            if callee_name and callee_name[0].isupper():
                # Skip common non-constructor patterns
                if callee_name in (
                    "Path",
                    "Optional",
                    "List",
                    "Dict",
                    "Set",
                    "Tuple",
                    "Any",
                    "Union",
                ):
                    continue

                count += 1
                instantiated_classes.append(callee_name)

    return count, instantiated_classes


def scan_file(path: Path, max_instantiations: int) -> List[Tuple[Path, str, int, int, List[str]]]:
    """Return list of (path, class_name, line, count, classes) for violations."""
    source = path.read_text()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise RuntimeError(f"failed to parse Python source: {path} ({exc})") from exc

    violations: List[Tuple[Path, str, int, int, List[str]]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Check __init__ and __post_init__ methods
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            if item.name not in ("__init__", "__post_init__"):
                continue

            count, instantiated = count_instantiations(item)
            if count > max_instantiations:
                violations.append(
                    (path, node.name, node.lineno, count, instantiated)
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
            f"dependency_guard: failed to traverse {root}: {exc}",
            file=sys.stderr,
        )
        return 1

    for file_path in file_iter:
        resolved = file_path.resolve()
        if is_excluded(resolved, exclusions):
            continue
        try:
            entries = scan_file(resolved, args.max_instantiations)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        for entry_path, class_name, lineno, count, instantiated in entries:
            try:
                relative = entry_path.resolve().relative_to(repo_root)
            except ValueError:
                relative = entry_path

            classes_str = ", ".join(instantiated[:5])
            if len(instantiated) > 5:
                classes_str += f", ... ({len(instantiated) - 5} more)"

            violations.append(
                f"{relative}:{lineno} class {class_name} instantiates {count} dependencies "
                f"(limit {args.max_instantiations}) - [{classes_str}]"
            )

    if violations:
        header = (
            "Classes with too many dependency instantiations detected. "
            "Consider dependency injection or extracting coordinators:"
        )
        print(header, file=sys.stderr)
        for violation in sorted(violations):
            print(f"  - {violation}", file=sys.stderr)
        print(
            "\nTip: Pass dependencies via __init__ parameters instead of instantiating them internally",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
