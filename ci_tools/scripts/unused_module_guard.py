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
from typing import Dict, List, Optional, Set, Tuple

from ci_tools.scripts.guard_common import (
    iter_ast_nodes,
    iter_python_files,
    parse_python_ast,
)


class ImportCollector(ast.NodeVisitor):  # pylint: disable=invalid-name
    """Collects all import statements from a Python file."""

    def __init__(self, file_path: Optional[Path] = None, root: Optional[Path] = None):
        self.imports: Set[str] = set()
        self.file_path = file_path
        self.root = root

    def visit_Import(self, node: ast.Import) -> None:  # pylint: disable=invalid-name
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

    def _resolve_relative_import(self, node: ast.ImportFrom) -> None:
        """Handle relative imports like 'from . import X'."""
        if not (self.file_path and self.root):
            return

        file_module = get_module_name(self.file_path, self.root)
        if not file_module:
            return

        parts = file_module.split(".")
        if node.level > len(parts):
            return

        # Calculate base module path based on relative level
        base_parts = parts[: -node.level + 1] if node.level > 1 else parts[:-1]
        base_module = ".".join(base_parts) if base_parts else ""

        # Register imported names
        for alias in node.names:
            if alias.name != "*":
                if base_module:
                    self.imports.add(f"{base_module}.{alias.name}")
                else:
                    self.imports.add(alias.name)

    def _resolve_absolute_import(self, module: str, names: list) -> None:
        """Handle absolute imports like 'from foo import bar'."""
        # Strip src. prefix if present
        if module.startswith("src."):
            module = module[4:]

        # Add module and all parent modules
        parts = module.split(".")
        for i in range(len(parts)):
            self.imports.add(".".join(parts[: i + 1]))

        # Add imported names as submodules
        for alias in names:
            if alias.name != "*":
                self.imports.add(f"{module}.{alias.name}")

    # pylint: disable=invalid-name
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Visit 'from foo import bar' statements."""
        if node.module is None and node.level > 0:
            self._resolve_relative_import(node)
        elif node.module:
            self._resolve_absolute_import(node.module, node.names)

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

    for py_file in iter_python_files(root):
        tree = parse_python_ast(py_file, raise_on_error=False)
        if tree is None:
            continue

        collector = ImportCollector(file_path=py_file, root=root)
        collector.visit(tree)
        all_imports.update(collector.imports)

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


SUSPICIOUS_PATTERNS: Tuple[str, ...] = (
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
)

FALSE_POSITIVE_RULES: Dict[str, Tuple[str, ...]] = {
    "_temp": ("temperature", "max_temp"),
    "_2": ("phase_2", "_v2"),
}


def _is_false_positive_for_pattern(stem: str, pattern: str) -> bool:
    """Check if a stem matches false positive rules for a specific pattern."""
    if pattern in FALSE_POSITIVE_RULES:
        # Check if any exclusion marker is in the stem
        for marker in FALSE_POSITIVE_RULES[pattern]:
            if marker in stem:
                return True
    return False


def _duplicate_reason(stem: str) -> Optional[str]:
    """Check if a stem contains suspicious patterns, accounting for false positives."""
    for pattern in SUSPICIOUS_PATTERNS:
        if pattern in stem:
            # Check if this is a false positive for this specific pattern
            if not _is_false_positive_for_pattern(stem, pattern):
                return f"Suspicious duplicate pattern '{pattern}' in filename"
    return None


def find_suspicious_duplicates(root: Path) -> List[Tuple[Path, str]]:
    """
    Find files with suspicious naming patterns that suggest duplicates.

    Args:
        root: Root directory to search

    Returns:
        List of (file_path, reason) tuples
    """
    duplicates: List[Tuple[Path, str]] = []

    for py_file in iter_python_files(root):
        reason = _duplicate_reason(py_file.stem)
        if reason:
            duplicates.append((py_file, reason))

    return duplicates


def _collect_all_imports_with_parent(root: Path) -> Set[str]:
    imports = collect_all_imports(root)
    parent = root.parent
    if parent.exists():
        imports.update(collect_all_imports(parent))
    return imports


def _is_main_guard_node(node: ast.If) -> bool:
    """Check if an If node is a '__name__ == "__main__"' guard."""
    if not isinstance(node.test, ast.Compare):
        return False
    if not isinstance(node.test.left, ast.Name):
        return False
    if node.test.left.id != "__name__":
        return False
    if len(node.test.comparators) != 1:
        return False
    comparator = node.test.comparators[0]
    return isinstance(comparator, ast.Constant) and comparator.value == "__main__"


def _has_main_function(tree: ast.AST) -> bool:
    """Check if AST contains a main() function definition."""
    return any(
        isinstance(node, ast.FunctionDef) and node.name == "main"
        for node in iter_ast_nodes(tree, ast.FunctionDef)
    )


def _has_main_guard(tree: ast.AST) -> bool:
    """Check if AST contains if __name__ == '__main__' pattern."""
    return any(
        isinstance(node, ast.If) and _is_main_guard_node(node)
        for node in iter_ast_nodes(tree, ast.If)
    )


def _is_cli_entry_point(py_file: Path) -> bool:
    """
    Check if a file is a CLI entry point (has main() and if __name__ == "__main__").

    CLI entry points are meant to be executed directly (e.g., python -m module)
    rather than imported, so they don't need to appear in import statements.
    """
    tree = parse_python_ast(py_file, raise_on_error=False)
    if tree is None:
        return False

    return _has_main_guard(tree) and _has_main_function(tree)


def _should_skip_file(py_file: Path, exclude_patterns: List[str]) -> bool:
    # Defense in depth: skip __pycache__ even though iter_python_files filters it
    if "__pycache__" in str(py_file):
        return True
    if any(pattern in str(py_file) for pattern in exclude_patterns):
        return True
    # Skip __main__.py and main.py as they are entry points
    if py_file.name in ("__main__.py", "main.py"):
        return True
    # Skip CLI entry points (files with main() and if __name__ == "__main__")
    return _is_cli_entry_point(py_file)


def _check_exact_match(
    module_name: str, file_stem: str, all_imports: Set[str], root: Path
) -> bool:
    """Check for exact module name matches."""
    if module_name in all_imports:
        return True
    if f"src.{module_name}" in all_imports:
        return True
    if file_stem in all_imports:
        return True
    # Check if root directory name is prepended (e.g., ci_tools.scripts.guard_common)
    if f"{root.name}.{module_name}" in all_imports:
        return True
    return False


def _check_child_imported(module_name: str, all_imports: Set[str]) -> bool:
    """Check if any child module is imported."""
    for imported in all_imports:
        if imported.startswith(module_name + "."):
            return True
        if imported.startswith(f"src.{module_name}."):
            return True
    return False


def _has_specific_child_imports(
    parent: str, module_name: str, all_imports: Set[str]
) -> bool:
    """Check if parent has specific child imports that exclude this module."""
    return any(
        imp.startswith(parent + ".") and imp != module_name for imp in all_imports
    )


def _check_parent_imported(module_name: str, all_imports: Set[str]) -> bool:
    """Check if a parent module is imported wholesale."""
    module_parts = module_name.split(".")
    for i in range(len(module_parts) - 1):
        parent = ".".join(module_parts[: i + 1])
        if parent in all_imports or f"src.{parent}" in all_imports:
            if not _has_specific_child_imports(parent, module_name, all_imports):
                return True
    return False


def _module_is_imported(
    module_name: str,
    file_stem: str,
    all_imports: Set[str],
    root: Path,
) -> bool:
    if not module_name:
        return True

    if _check_exact_match(module_name, file_stem, all_imports, root):
        return True

    if _check_child_imported(module_name, all_imports):
        return True

    if _check_parent_imported(module_name, all_imports):
        return True

    return False


def find_unused_modules(
    root: Path, exclude_patterns: Optional[List[str]] = None
) -> List[Tuple[Path, str]]:
    """
    Find Python modules that are never imported.

    Args:
        root: Root directory to search
        exclude_patterns: Patterns to exclude (e.g., ['__init__.py', 'test_'])

    Returns:
        List of (file_path, reason) tuples for unused modules
    """
    exclude_patterns = list(exclude_patterns or [])
    all_imports = _collect_all_imports_with_parent(root)
    unused: List[Tuple[Path, str]] = []

    for py_file in iter_python_files(root):
        if _should_skip_file(py_file, exclude_patterns):
            continue

        module_name = get_module_name(py_file, root)
        if _module_is_imported(module_name, py_file.stem, all_imports, root):
            continue

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
        help="Root directory to check (initial: src)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Enable strict mode (fail on suspicious duplicates too)",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        help="Patterns to exclude from unused checks",
    )
    parser.set_defaults(root=Path("src"), exclude=["__init__.py", "conftest.py"])

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
