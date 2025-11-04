"""Shared utilities for guard scripts.

This module provides common functionality used across multiple guard scripts
to eliminate code duplication and ensure consistent behavior.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
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
        msg = f"path does not exist: {root}"
        raise OSError(msg)
    if root.is_file():
        if root.suffix == ".py":
            yield root
        return
    yield from root.rglob("*.py")


def parse_python_ast(path: Path, *, raise_on_error: bool = True) -> ast.AST | None:
    """Parse a Python file into an AST.

    Args:
        path: Path to the Python file to parse
        raise_on_error: If True, raise RuntimeError on parse failure; if False, return None

    Returns:
        AST tree for the file, or None if parsing fails and raise_on_error is False

    Raises:
        RuntimeError: If the file cannot be parsed due to syntax errors and raise_on_error is True
    """
    try:
        source = path.read_text()
        return ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError, FileNotFoundError, OSError) as exc:
        if raise_on_error:
            msg = f"failed to parse Python source: {path} ({exc})"
            raise RuntimeError(msg) from exc
        return None


def detect_repo_root() -> Path:
    """Detect the repository root directory.

    Attempts to use git command first for reliability, falls back to
    directory walking if git is unavailable.

    Returns:
        Path to repository root (directory containing .git), or current
        working directory if not found

    Example:
        >>> root = detect_repo_root()
        >>> assert (root / ".git").exists() or root == Path.cwd()
    """
    # Try git command first (most reliable)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        candidate = Path(result.stdout.strip())
        if candidate.exists():
            return candidate
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Fall back to directory walking
    current = Path.cwd().resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return Path.cwd().resolve()


def relative_path(
    path: Path, repo_root: Path | None = None, *, as_string: bool = False
) -> Path | str:
    """Convert a path to repo-relative format.

    This unified function consolidates the functionality of the former
    normalize_path() and make_relative_path() functions.

    Args:
        path: Path to convert (absolute or relative)
        repo_root: Repository root (defaults to current directory)
        as_string: If True, return string with forward slashes; if False, return Path

    Returns:
        Path object or string representation, relative to repo_root if possible
    """
    if repo_root is None:
        repo_root = Path.cwd()

    try:
        relative = path.resolve().relative_to(repo_root)
    except ValueError:
        # Path is outside repo_root, return as-is
        relative = path

    if as_string:
        return str(relative).replace("\\", "/")
    return relative


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


def count_ast_node_lines(node: ast.AST) -> int:
    """Count lines spanned by an AST node.

    Args:
        node: AST node (function, class, etc.)

    Returns:
        Number of lines spanned by the node, or 0 if end_lineno is not available
    """
    if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
        return 0
    lineno = getattr(node, "lineno", None)
    end_lineno = getattr(node, "end_lineno", None)
    if lineno is None or end_lineno is None:
        return 0
    return end_lineno - lineno + 1


def get_class_line_span(node: ast.ClassDef) -> tuple[int, int]:
    """Get the start and end line numbers of a class definition.

    Args:
        node: ClassDef AST node

    Returns:
        Tuple of (start_line, end_line)
    """
    start = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", None)
    if end is None:
        # Fallback: walk all child nodes to find maximum line number
        end = start
        for inner in ast.walk(node):
            inner_end = getattr(inner, "end_lineno", None)
            if inner_end is not None and inner_end > end:
                end = inner_end
    return start, end


def count_class_methods(node: ast.ClassDef) -> tuple[int, int]:
    """Count public and total methods in a class.

    Excludes:
        - Dunder methods (__init__, __str__, etc.)
        - Properties (@property decorated methods)

    Args:
        node: ClassDef AST node

    Returns:
        Tuple of (public_method_count, total_method_count)
    """
    public_count = 0
    total_count = 0

    for item in node.body:
        if not isinstance(item, ast.FunctionDef):
            continue

        # Skip dunder methods and name-mangled methods
        if item.name.startswith("__"):
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


def iter_ast_nodes(
    tree: ast.AST, node_types: type[ast.AST] | tuple[type[ast.AST], ...]
) -> Iterable[ast.AST]:
    """Iterate over AST nodes of specified types.

    This helper consolidates the common pattern of walking an AST and filtering
    by node type, reducing code duplication across guard scripts.

    Args:
        tree: AST tree to walk
        node_types: Single node type or tuple of node types to filter for

    Yields:
        AST nodes matching the specified types

    Example:
        >>> for func in iter_ast_nodes(tree, (ast.FunctionDef, ast.AsyncFunctionDef)):
        ...     print(func.name)
    """
    for node in ast.walk(tree):
        if isinstance(node, node_types):
            yield node


def count_significant_lines(tree: ast.AST) -> int:
    """Count significant (non-empty, non-comment) lines in an AST.

    This provides a more accurate module size metric than raw line counts.

    Args:
        tree: Parsed AST tree

    Returns:
        Number of lines that contain executable code or definitions
    """
    # Collect all line numbers that contain AST nodes
    lines_with_code = set()
    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", None)
        if lineno is not None:
            lines_with_code.add(lineno)
        end_lineno = getattr(node, "end_lineno", None)
        if end_lineno is not None and lineno is not None:
            # Add all lines in the span
            for line_num in range(lineno, end_lineno + 1):
                lines_with_code.add(line_num)
    return len(lines_with_code)


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
    """Base class for guard scripts.

    Subclasses implement setup_parser(), scan_file(), get_violations_header().
    """

    def __init__(self, name: str, description: str, default_root: Path = Path("src")):
        self.name, self.description, self.default_root = name, description, default_root
        self.repo_root = Path.cwd()

    @abstractmethod
    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        """Add script-specific arguments."""

    @abstractmethod
    def scan_file(self, path: Path, args: argparse.Namespace) -> List[str]:
        """Return list of violation messages for this file."""

    @abstractmethod
    def get_violations_header(self, args: argparse.Namespace) -> str:
        """Return header message for violations report."""

    # pylint: disable=unused-argument
    def get_violations_footer(self, args: argparse.Namespace) -> Optional[str]:
        """Return optional footer message for violations report."""
        return None

    def parse_args(self, argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
        """Parse command-line arguments for this guard script."""
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

    @classmethod
    def main(cls, argv: Optional[Iterable[str]] = None) -> int:
        """Standard main entry point for guard scripts.

        This method provides a generic main() implementation for all guards
        that inherit from GuardRunner, eliminating boilerplate.

        Args:
            argv: Command-line arguments (defaults to sys.argv)

        Returns:
            Exit code: 0 if no violations, 1 otherwise
        """
        guard = cls()  # type: ignore[call-arg]  # pylint: disable=no-value-for-parameter
        return guard.run(argv)
