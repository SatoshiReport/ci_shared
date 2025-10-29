"""Fail the build when Python classes exceed configured line limits."""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect oversized Python classes that need refactoring."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("src"),
        help="Directory to scan for Python modules (defaults to ./src).",
    )
    parser.add_argument(
        "--max-class-lines",
        type=int,
        default=400,
        help="Maximum allowed number of lines per class definition.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        type=Path,
        default=[],
        help="Path prefix to exclude from the scan (may be passed multiple times).",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help=(
            "Optional file containing classes to temporarily ignore. "
            "Use format '<path>:<ClassName>' per line."
        ),
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


def scan_file(path: Path, limit: int) -> List[Tuple[Path, str, int, int]]:
    source = path.read_text()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:  # pragma: no cover - surfaces during CI only
        raise RuntimeError(f"failed to parse Python source: {path} ({exc})") from exc

    violations: List[Tuple[Path, str, int, int]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            start, end = class_line_span(node)
            length = end - start + 1
            if length > limit:
                violations.append((path, node.name, start, length))
    return violations


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    exclusions = [path.resolve() for path in args.exclude]
    repo_root = Path.cwd()

    baseline_entries = set()
    if args.baseline:
        content = args.baseline.read_text().splitlines()
        for line in content:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            baseline_entries.add(stripped)
    baseline_hits: set[str] = set()

    violations: List[str] = []
    try:
        file_iter = list(iter_python_files(root))
    except OSError as exc:  # pragma: no cover
        print(f"structure_guard: failed to traverse {root}: {exc}", file=sys.stderr)
        return 1

    for file_path in file_iter:
        resolved = file_path.resolve()
        if is_excluded(resolved, exclusions):
            continue
        try:
            entries = scan_file(resolved, args.max_class_lines)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        for entry_path, class_name, start, length in entries:
            try:
                relative = entry_path.resolve().relative_to(repo_root)
            except ValueError:
                relative = entry_path
            key = f"{relative}:{class_name}"
            if key in baseline_entries:
                baseline_hits.add(key)
                continue
            violations.append(
                f"{relative}:{start} class {class_name} spans {length} lines "
                f"(limit {args.max_class_lines})"
            )

    if violations:
        header = (
            "Oversized classes detected. Refactor the following definitions "
            f"to stay within {args.max_class_lines} lines:"
        )
        print(header, file=sys.stderr)
        for violation in sorted(violations):
            print(f"  - {violation}", file=sys.stderr)
        return 1

    unused_baseline = baseline_entries - baseline_hits
    if unused_baseline:
        print(
            "structure_guard: baseline entries not encountered; "
            "consider removing them:",
            file=sys.stderr,
        )
        for entry in sorted(unused_baseline):
            print(f"  - {entry}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
