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


def count_instantiations(func_node: ast.FunctionDef) -> Tuple[int, List[str]]:
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


def _format_violation(
    entry_path: Path,
    *,
    class_name: str,
    lineno: int,
    count: int,
    instantiated: List[str],
    limit: int,
    repo_root: Path,
) -> str:
    try:
        relative = entry_path.resolve().relative_to(repo_root)
    except ValueError:
        relative = entry_path
    classes_str = ", ".join(instantiated[:5])
    if len(instantiated) > 5:
        classes_str += f", ... ({len(instantiated) - 5} more)"
    return (
        f"{relative}:{lineno} class {class_name} instantiates {count} dependencies "
        f"(limit {limit}) - [{classes_str}]"
    )


def _collect_file_violations(
    path: Path,
    *,
    max_instantiations: int,
    repo_root: Path,
) -> List[str]:
    entries = scan_file(path, max_instantiations)
    return [
        _format_violation(
            entry_path,
            class_name=class_name,
            lineno=lineno,
            count=count,
            instantiated=instantiated,
            limit=max_instantiations,
            repo_root=repo_root,
        )
        for entry_path, class_name, lineno, count, instantiated in entries
    ]


def _print_violation_report(violations: List[str], limit: int) -> None:
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


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    exclusions = [path.resolve() for path in args.exclude]
    repo_root = Path.cwd()

    try:
        file_iter = list(iter_python_files(root))
    except OSError as exc:
        print(f"dependency_guard: failed to traverse {root}: {exc}", file=sys.stderr)
        return 1

    violations: List[str] = []
    for file_path in file_iter:
        resolved = file_path.resolve()
        if is_excluded(resolved, exclusions):
            continue
        try:
            violations.extend(
                _collect_file_violations(
                    resolved,
                    max_instantiations=args.max_instantiations,
                    repo_root=repo_root,
                )
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    if violations:
        _print_violation_report(violations, args.max_instantiations)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
