"""Fail the build when functions exceed configured line limits."""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect oversized functions that should be refactored."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("src"),
        help="Directory to scan for Python files (defaults to ./src).",
    )
    parser.add_argument(
        "--max-function-lines",
        type=int,
        default=80,
        help="Maximum allowed lines per function (defaults to 80).",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        type=Path,
        default=[],
        help="Path prefix to exclude from the scan.",
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
        except (ValueError, AttributeError):
            continue
    return False


def count_function_lines(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Count lines spanned by a function definition."""
    if not hasattr(node, "end_lineno") or node.end_lineno is None:
        return 0
    return node.end_lineno - node.lineno + 1


def scan_file(
    path: Path, limit: int
) -> List[Tuple[str, str, int, int]]:
    """Return list of (file, function, lineno, line_count) for violations."""
    try:
        content = path.read_text()
        tree = ast.parse(content, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        print(f"function_size_guard: failed to parse {path}: {exc}", file=sys.stderr)
        return []

    violations: List[Tuple[str, str, int, int]] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            line_count = count_function_lines(node)
            if line_count > limit:
                violations.append((str(path), node.name, node.lineno, line_count))

    return violations


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    exclusions = [path.resolve() for path in args.exclude]
    repo_root = Path.cwd()

    all_violations: List[str] = []

    try:
        file_iter = list(iter_python_files(root))
    except OSError as exc:
        print(f"function_size_guard: failed to traverse {root}: {exc}", file=sys.stderr)
        return 1

    for file_path in file_iter:
        resolved = file_path.resolve()
        if is_excluded(resolved, exclusions):
            continue

        file_violations = scan_file(resolved, args.max_function_lines)

        for file_str, func_name, lineno, line_count in file_violations:
            try:
                relative = Path(file_str).resolve().relative_to(repo_root)
            except ValueError:
                relative = Path(file_str)

            all_violations.append(
                f"{relative}::{func_name} (line {lineno}) contains {line_count} lines "
                f"(limit {args.max_function_lines})"
            )

    if all_violations:
        header = (
            f"Oversized functions detected. Refactor functions to stay within "
            f"{args.max_function_lines} lines:"
        )
        print(header, file=sys.stderr)
        for violation in sorted(all_violations):
            print(f"  - {violation}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
