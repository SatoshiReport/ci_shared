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
from typing import Dict, Iterable, List, Optional, Set, Tuple


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect classes with excessive inheritance depth."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("src"),
        help="Directory to scan for Python modules (defaults to ./src).",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=2,
        help="Maximum allowed inheritance depth (default: 2, meaning class → parent → grandparent).",
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
    for base in bases:
        # Skip common base classes that don't count as "real" inheritance
        if base in ("object", "Protocol", "ABC"):
            continue
        base_depth = calculate_depth(base, hierarchy, visited.copy())
        max_base_depth = max(max_base_depth, base_depth)

    return max_base_depth + 1


def scan_file(
    path: Path, max_depth: int
) -> List[Tuple[Path, str, int, int, List[str]]]:
    """Return list of (path, class_name, line_number, depth, base_chain) for violations."""
    source = path.read_text()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise RuntimeError(f"failed to parse Python source: {path} ({exc})") from exc

    hierarchy = build_class_hierarchy(tree)
    violations: List[Tuple[Path, str, int, int, List[str]]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            depth = calculate_depth(node.name, hierarchy)
            if depth > max_depth:
                base_names = extract_base_names(node)
                violations.append((path, node.name, node.lineno, depth, base_names))

    return violations


def _format_inheritance_violation(
    entry_path: Path,
    *,
    class_name: str,
    lineno: int,
    depth: int,
    base_names: List[str],
    limit: int,
    repo_root: Path,
) -> str:
    try:
        relative = entry_path.resolve().relative_to(repo_root)
    except ValueError:
        relative = entry_path
    bases_str = ", ".join(base_names) if base_names else "(none)"
    return (
        f"{relative}:{lineno} class {class_name} has inheritance "
        f"depth {depth} (limit {limit}) - bases: {bases_str}"
    )


def _collect_inheritance_violations(
    path: Path,
    *,
    max_depth: int,
    repo_root: Path,
) -> List[str]:
    entries = scan_file(path, max_depth)
    return [
        _format_inheritance_violation(
            entry_path,
            class_name=class_name,
            lineno=lineno,
            depth=depth,
            base_names=base_names,
            limit=max_depth,
            repo_root=repo_root,
        )
        for entry_path, class_name, lineno, depth, base_names in entries
    ]


def _print_inheritance_report(violations: List[str], limit: int) -> None:
    header = (
        "Deep inheritance detected. Refactor the following classes "
        f"to stay within depth {limit} (prefer composition over inheritance):"
    )
    print(header, file=sys.stderr)
    for violation in sorted(violations):
        print(f"  - {violation}", file=sys.stderr)
    print(
        "\nTip: Replace mixin inheritance with service objects injected via __init__",
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
        print(f"inheritance_guard: failed to traverse {root}: {exc}", file=sys.stderr)
        return 1

    violations: List[str] = []
    for file_path in file_iter:
        resolved = file_path.resolve()
        if is_excluded(resolved, exclusions):
            continue
        try:
            violations.extend(
                _collect_inheritance_violations(
                    resolved,
                    max_depth=args.max_depth,
                    repo_root=repo_root,
                )
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    if violations:
        _print_inheritance_report(violations, args.max_depth)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
