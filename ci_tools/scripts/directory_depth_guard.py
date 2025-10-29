"""Fail the build when directory nesting exceeds configured depth."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect deeply nested directory structures that harm navigability."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("src"),
        help="Directory to scan (defaults to ./src).",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=5,
        help="Maximum allowed directory nesting depth (defaults to 5).",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        type=str,
        default=[],
        help="Directory name patterns to exclude (e.g., '__pycache__').",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def calculate_depth(path: Path, root: Path) -> int:
    """Calculate nesting depth relative to root."""
    try:
        relative = path.relative_to(root)
        return len(relative.parts)
    except ValueError:
        return 0


def should_exclude(path: Path, exclusions: List[str]) -> bool:
    """Check if path matches any exclusion pattern."""
    for excluded in exclusions:
        if excluded in path.name or path.name.startswith("."):
            return True
    return False


def scan_directories(
    root: Path, max_depth: int, exclusions: List[str]
) -> List[Tuple[Path, int]]:
    """Recursively scan directories and return violations."""
    violations: List[Tuple[Path, int]] = []

    def _scan(current: Path, depth: int) -> None:
        if should_exclude(current, exclusions):
            return

        if depth > max_depth:
            violations.append((current, depth))

        try:
            for item in current.iterdir():
                if item.is_dir():
                    _scan(item, depth + 1)
        except PermissionError:
            pass  # Skip directories we can't read

    for item in root.iterdir():
        if item.is_dir():
            _scan(item, 1)

    return violations


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()

    if not root.exists():
        print(f"directory_depth_guard: root path does not exist: {root}", file=sys.stderr)
        return 1

    exclusions = args.exclude + ["__pycache__", ".pytest_cache", ".mypy_cache"]
    violations = scan_directories(root, args.max_depth, exclusions)

    if violations:
        header = (
            f"Directory nesting exceeds {args.max_depth} levels. "
            "Consider flattening the following paths:"
        )
        print(header, file=sys.stderr)
        for path, depth in sorted(violations, key=lambda x: x[1], reverse=True):
            relative = path.relative_to(root.parent)
            print(f"  - {relative} (depth: {depth})", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
