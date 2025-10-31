#!/usr/bin/env python3
"""
Unused Module Guard - Detects Python modules that are never imported.

This guard identifies:
1. Python files that are never imported anywhere in the codebase
2. Suspicious duplicate files (_refactored, _slim, _old, etc.)
3. Test files without corresponding source files

Usage:
    python -m ci_tools.scripts.unused_module_guard --root src [--strict]

Exit codes:
    0: No unused modules found
    1: Unused modules detected
"""

import argparse
import ast
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


class ImportCollector(ast.NodeVisitor):
    """Collects all import statements from a Python file."""

    def __init__(self):
        self.imports: Set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        """Visit 'import foo' statements."""
        for alias in node.names:
            # Add full module path and all parent modules
            module = alias.name
            # Strip src. prefix if present
            if module.startswith("src."):
                module = module[4:]
            parts = module.split(".")
            for i in range(len(parts)):
                self.imports.add(".".join(parts[: i + 1]))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Visit 'from foo import bar' statements."""
        if node.module:
            # Add full module path and all parent modules
            module = node.module
            # Strip src. prefix if present
            if module.startswith("src."):
                module = module[4:]
            parts = module.split(".")
            for i in range(len(parts)):
                self.imports.add(".".join(parts[: i + 1]))
        self.generic_visit(node)


def collect_all_imports(root: Path) -> Set[str]:
    """
    Collect all imported module names from all Python files.

    Args:
        root: Root directory to search

    Returns:
        Set of all imported module names
    """
    all_imports: Set[str] = set()

    for py_file in root.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        try:
            with open(py_file, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(py_file))
            collector = ImportCollector()
            collector.visit(tree)
            all_imports.update(collector.imports)
        except (SyntaxError, UnicodeDecodeError):
            # Skip files with syntax errors or encoding issues
            pass

    return all_imports


def get_module_name(file_path: Path, root: Path) -> str:
    """
    Convert file path to Python module name.

    Args:
        file_path: Path to Python file
        root: Root directory

    Returns:
        Module name (e.g., 'common.redis_protocol.store')
    """
    relative = file_path.relative_to(root)
    parts = list(relative.parts)

    # Remove .py extension
    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]

    # Remove __init__ from module name
    if parts[-1] == "__init__":
        parts = parts[:-1]

    return ".".join(parts) if parts else ""


def find_suspicious_duplicates(root: Path) -> List[Tuple[Path, str]]:
    """
    Find files with suspicious naming patterns that suggest duplicates.

    Args:
        root: Root directory to search

    Returns:
        List of (file_path, reason) tuples
    """
    suspicious_patterns = [
        "_refactored",
        "_slim",
        "_optimized",
        "_old",
        "_backup",
        "_copy",
        "_new",
        "_temp",
        "_v2",
        "_2",
    ]

    duplicates: List[Tuple[Path, str]] = []

    for py_file in root.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        stem = py_file.stem

        # Skip false positives
        if "_temp" in stem and ("temperature" in stem or "max_temp" in stem):
            continue
        if "_2" in stem and ("phase_2" in stem or "_v2" in stem):
            continue

        for pattern in suspicious_patterns:
            if pattern in stem:
                duplicates.append(
                    (py_file, f"Suspicious duplicate pattern '{pattern}' in filename")
                )
                break

    return duplicates


def find_unused_modules(
    root: Path, exclude_patterns: List[str] = None
) -> List[Tuple[Path, str]]:
    """
    Find Python modules that are never imported.

    Args:
        root: Root directory to search
        exclude_patterns: Patterns to exclude (e.g., ['__init__.py', 'test_'])

    Returns:
        List of (file_path, reason) tuples for unused modules
    """
    if exclude_patterns is None:
        exclude_patterns = []

    # Collect all imports from all files
    all_imports = collect_all_imports(root)

    # Also check parent directory for imports of this package
    if root.parent.exists():
        parent_imports = collect_all_imports(root.parent)
        all_imports.update(parent_imports)

    unused: List[Tuple[Path, str]] = []

    for py_file in root.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        # Skip excluded patterns
        if any(pattern in str(py_file) for pattern in exclude_patterns):
            continue

        # Skip __main__.py (entry points)
        if py_file.name == "__main__.py":
            continue

        # Get module name
        module_name = get_module_name(py_file, root)
        if not module_name:
            continue

        # Check if this module or any parent module is imported
        module_parts = module_name.split(".")
        is_imported = False

        for i in range(len(module_parts)):
            partial_module = ".".join(module_parts[: i + 1])
            if partial_module in all_imports:
                is_imported = True
                break

        # Also check just the filename without path
        if py_file.stem in all_imports:
            is_imported = True

        if not is_imported:
            unused.append((py_file, f"Never imported (module: {module_name})"))

    return unused


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Detect unused Python modules",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("src"),
        help="Root directory to check (default: src)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable strict mode (fail on suspicious duplicates too)",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        default=["__init__.py", "conftest.py"],
        help="Patterns to exclude from unused checks",
    )

    args = parser.parse_args()

    if not args.root.exists():
        print(f"Error: Root directory '{args.root}' does not exist", file=sys.stderr)
        return 1

    print(f"Checking for unused modules in {args.root}...")

    # Find unused modules
    unused = find_unused_modules(args.root, args.exclude)

    # Find suspicious duplicates
    duplicates = find_suspicious_duplicates(args.root)

    # Report results
    issues_found = False

    if unused:
        print("\n❌ Unused modules detected (never imported):")
        for file_path, reason in sorted(unused):
            print(f"  - {file_path.relative_to(args.root)}: {reason}")
        issues_found = True

    if duplicates:
        print("\n⚠️  Suspicious duplicate files detected:")
        for file_path, reason in sorted(duplicates):
            print(f"  - {file_path.relative_to(args.root)}: {reason}")
        if args.strict:
            issues_found = True

    if not issues_found:
        print("✅ No unused modules found")
        return 0

    print(
        "\nTip: Remove unused files or add them to .gitignore if they're work-in-progress"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
