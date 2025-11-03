"""Shared utilities for guard scripts.

This module provides common functionality used across multiple guard scripts
to eliminate code duplication and ensure consistent behavior.
"""

from __future__ import annotations

import argparse
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Union


def iter_python_files(root: Union[Path, Sequence[Path]]) -> Iterable[Path]:
    """Iterate over all Python files in a directory tree or single file.

    Args:
        root: Directory to scan recursively, single Python file, or sequence of paths

    Yields:
        Path objects for each .py file found

    Raises:
        OSError: If a root path does not exist
    """
    # Handle both single Path and Sequence[Path] for maximum compatibility
    if isinstance(root, (list, tuple)):
        for base in root:
            if not base.exists():
                continue
            yield from iter_python_files(base)
        return

    # Single Path handling - at this point root must be Path due to early return above
    assert isinstance(root, Path)  # Type narrowing for pyright
    if not root.exists():
        raise OSError(f"path does not exist: {root}")
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    for candidate in root.rglob("*.py"):
        yield candidate


def normalize_path(path: Path, repo_root: Path | None = None) -> str:
    """Normalize a path relative to repo root for display.

    Args:
        path: Path to normalize
        repo_root: Repository root (defaults to current directory)

    Returns:
        Normalized path string with forward slashes
    """
    if repo_root is None:
        repo_root = Path.cwd()
    try:
        return str(path.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def make_relative_path(path: Path, repo_root: Path) -> Path:
    """Convert an absolute path to repo-relative path.

    Args:
        path: Path to convert (typically absolute)
        repo_root: Repository root directory

    Returns:
        Relative path if possible, otherwise the original path
    """
    try:
        return path.resolve().relative_to(repo_root)
    except ValueError:
        return path


def is_excluded(path: Path, exclusions: List[Path]) -> bool:
    """Check if a path should be excluded based on prefix matching.

    Args:
        path: Path to check for exclusion
        exclusions: List of path prefixes to exclude

    Returns:
        True if path matches any exclusion prefix, False otherwise
    """
    for excluded in exclusions:
        try:
            if path.is_relative_to(excluded):
                return True
        except ValueError:
            continue
    return False


def create_guard_parser(
    description: str, default_root: Path = Path("src")
) -> argparse.ArgumentParser:
    """Create an argument parser with common guard script options.

    Args:
        description: Description of what the guard script does
        default_root: Default directory to scan (defaults to ./src)

    Returns:
        ArgumentParser with --root and --exclude arguments pre-configured
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--root",
        type=Path,
        default=default_root,
        help=f"Directory to scan for Python files (default: {default_root}).",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        type=Path,
        default=[],
        help="Path prefix to exclude from the scan (may be passed multiple times).",
    )
    return parser


def report_violations(
    violations: List[str],
    header: str,
) -> None:
    """Print violations to stderr in a standard format.

    Args:
        violations: List of violation messages to report
        header: Header message describing the violation type
    """
    if not violations:
        return

    print(header, file=sys.stderr)
    for violation in sorted(violations):
        print(f"  - {violation}", file=sys.stderr)


class GuardRunner(ABC):
    """Base class for guard scripts. Subclasses implement setup_parser(), scan_file(), get_violations_header()."""

    def __init__(self, name: str, description: str, default_root: Path = Path("src")):
        self.name, self.description, self.default_root = name, description, default_root
        self.repo_root = Path.cwd()

    @abstractmethod
    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        """Add script-specific arguments."""
        pass

    @abstractmethod
    def scan_file(self, path: Path, args: argparse.Namespace) -> List[str]:
        """Return list of violation messages for this file."""
        pass

    @abstractmethod
    def get_violations_header(self, args: argparse.Namespace) -> str:
        """Return header message for violations report."""
        pass

    def get_violations_footer(self, args: argparse.Namespace) -> Optional[str]:
        return None

    def parse_args(self, argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
        parser = create_guard_parser(self.description, self.default_root)
        self.setup_parser(parser)
        return parser.parse_args(list(argv) if argv is not None else None)

    def run(self, argv: Optional[Iterable[str]] = None) -> int:
        """Run guard script. Returns 0 if no violations, 1 otherwise."""
        args = self.parse_args(argv)
        root, exclusions = args.root.resolve(), [p.resolve() for p in args.exclude]
        violations: List[str] = []
        try:
            file_iter = list(iter_python_files(root))
        except OSError as exc:
            print(f"{self.name}: failed to traverse {root}: {exc}", file=sys.stderr)
            return 1
        for file_path in file_iter:
            resolved = file_path.resolve()
            if is_excluded(resolved, exclusions):
                continue
            try:
                violations.extend(self.scan_file(resolved, args))
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                return 1
        if violations:
            report_violations(violations, self.get_violations_header(args))
            if footer := self.get_violations_footer(args):
                print(f"\n{footer}", file=sys.stderr)
            return 1
        return 0
