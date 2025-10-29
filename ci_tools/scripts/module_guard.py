"""Fail the build when Python modules exceed configured line limits."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect oversized Python modules that need refactoring."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("src"),
        help="Directory to scan for Python modules (defaults to ./src).",
    )
    parser.add_argument(
        "--max-module-lines",
        type=int,
        default=600,
        help="Maximum allowed number of lines per module (file).",
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
            "Optional file containing modules to temporarily ignore. "
            "Use format '<relative/path.py>' per line."
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


def count_lines(path: Path) -> int:
    """Count non-empty, non-comment-only lines in a Python module."""
    lines = path.read_text().splitlines()
    significant_lines = 0
    for line in lines:
        stripped = line.strip()
        # Count non-empty lines that aren't just comments
        if stripped and not stripped.startswith("#"):
            significant_lines += 1
    return significant_lines


def scan_file(path: Path, limit: int) -> Optional[Tuple[Path, int]]:
    """Return (path, line_count) if module exceeds limit, else None."""
    try:
        line_count = count_lines(path)
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"failed to read Python source: {path} ({exc})") from exc

    if line_count > limit:
        return (path, line_count)
    return None


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
        print(f"module_guard: failed to traverse {root}: {exc}", file=sys.stderr)
        return 1

    for file_path in file_iter:
        resolved = file_path.resolve()
        if is_excluded(resolved, exclusions):
            continue
        try:
            result = scan_file(resolved, args.max_module_lines)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        if result is not None:
            entry_path, line_count = result
            try:
                relative = entry_path.resolve().relative_to(repo_root)
            except ValueError:
                relative = entry_path

            key = str(relative)
            if key in baseline_entries:
                baseline_hits.add(key)
                continue

            violations.append(
                f"{relative} contains {line_count} lines "
                f"(limit {args.max_module_lines})"
            )

    if violations:
        header = (
            "Oversized modules detected. Refactor the following files "
            f"to stay within {args.max_module_lines} lines:"
        )
        print(header, file=sys.stderr)
        for violation in sorted(violations):
            print(f"  - {violation}", file=sys.stderr)
        return 1

    unused_baseline = baseline_entries - baseline_hits
    if unused_baseline:
        print(
            "module_guard: baseline entries not encountered; "
            "consider removing them:",
            file=sys.stderr,
        )
        for entry in sorted(unused_baseline):
            print(f"  - {entry}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
