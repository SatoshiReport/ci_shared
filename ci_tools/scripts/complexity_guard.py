#!/usr/bin/env python3
"""
Enforce complexity limits across the codebase.

Best practice limits:
- Cyclomatic complexity: ≤10 per function
- Cognitive complexity: ≤15 per function

Usage:
    python scripts/complexity_guard.py --root src
    python scripts/complexity_guard.py --root src --max-cyclomatic 10 --max-cognitive 15
"""

import argparse
import ast
import sys
from pathlib import Path
from typing import NamedTuple

from radon.complexity import cc_visit


class ComplexityViolation(NamedTuple):
    """Represents a complexity violation."""

    file_path: str
    function_name: str
    line_number: int
    cyclomatic: int
    cognitive: int
    violation_type: str


def calculate_cognitive_complexity(node: ast.FunctionDef) -> int:
    """
    Calculate cognitive complexity for a function.

    Cognitive complexity measures how difficult code is to understand,
    accounting for nested control structures and logical operators.
    """

    class CognitiveComplexityVisitor(ast.NodeVisitor):
        """AST visitor that calculates cognitive complexity of a function."""

        def __init__(self):
            self.complexity = 0
            self.nesting_level = 0

        def visit_If(self, node):  # pylint: disable=invalid-name
            """Visit If node and increment complexity based on nesting level."""
            self.complexity += 1 + self.nesting_level
            self.nesting_level += 1
            self.generic_visit(node)
            self.nesting_level -= 1

        def visit_While(self, node):  # pylint: disable=invalid-name
            """Visit While node and increment complexity based on nesting level."""
            self.complexity += 1 + self.nesting_level
            self.nesting_level += 1
            self.generic_visit(node)
            self.nesting_level -= 1

        def visit_For(self, node):  # pylint: disable=invalid-name
            """Visit For node and increment complexity based on nesting level."""
            self.complexity += 1 + self.nesting_level
            self.nesting_level += 1
            self.generic_visit(node)
            self.nesting_level -= 1

        def visit_ExceptHandler(self, node):  # pylint: disable=invalid-name
            """Visit ExceptHandler node and increment complexity based on nesting level."""
            self.complexity += 1 + self.nesting_level
            self.nesting_level += 1
            self.generic_visit(node)
            self.nesting_level -= 1

        def visit_BoolOp(self, node):  # pylint: disable=invalid-name
            """Visit BoolOp node and add complexity for each boolean condition."""
            # Each additional condition in a boolean expression adds complexity
            if isinstance(node.op, (ast.And, ast.Or)):
                self.complexity += len(node.values) - 1
            self.generic_visit(node)

        def visit_Lambda(self, node):  # pylint: disable=invalid-name
            """Visit Lambda node without counting nested lambdas as they're separate units."""
            # Don't count nested lambdas - they're separate cognitive units

    visitor = CognitiveComplexityVisitor()
    visitor.visit(node)
    return visitor.complexity


def check_file_complexity(  # pylint: disable=too-many-locals
    file_path: Path, max_cyclomatic: int, max_cognitive: int
) -> list[ComplexityViolation]:
    """Check complexity for all functions in a file."""
    violations = []

    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        # Get cyclomatic complexity using radon
        cyclomatic_results = cc_visit(content)

        # Parse AST for cognitive complexity
        tree = ast.parse(content)

        # Build map of function names to AST nodes
        function_nodes = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_nodes[node.name] = node

        # Check each function
        for result in cyclomatic_results:
            cyclomatic = result.complexity
            function_name = result.name
            line_number = result.lineno

            # Calculate cognitive complexity
            cognitive = 0
            if function_name in function_nodes:
                cognitive = calculate_cognitive_complexity(
                    function_nodes[function_name]
                )

            # Determine violations
            violation_types = []
            if cyclomatic > max_cyclomatic:
                violation_types.append(f"cyclomatic {cyclomatic}")
            if cognitive > max_cognitive:
                violation_types.append(f"cognitive {cognitive}")

            if violation_types:
                violations.append(
                    ComplexityViolation(
                        file_path=str(file_path),
                        function_name=function_name,
                        line_number=line_number,
                        cyclomatic=cyclomatic,
                        cognitive=cognitive,
                        violation_type=" & ".join(violation_types),
                    )
                )

    except (SyntaxError, UnicodeDecodeError, FileNotFoundError) as e:
        print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)

    return violations


def build_parser() -> argparse.ArgumentParser:
    """Create and configure the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Enforce complexity limits (cyclomatic ≤10, cognitive ≤15)"
    )
    parser.add_argument(
        "--root", type=Path, required=True, help="Root directory to scan"
    )
    parser.add_argument(
        "--max-cyclomatic",
        type=int,
        default=10,
        help="Maximum cyclomatic complexity (default: 10)",
    )
    parser.add_argument(
        "--max-cognitive",
        type=int,
        default=15,
        help="Maximum cognitive complexity (default: 15)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "Path relative to --root to exclude from scanning. "
            "May be provided multiple times."
        ),
    )
    return parser


def resolve_root(root: Path) -> Path:
    """Validate and resolve the root directory."""
    if not root.exists():
        print(f"Error: Directory {root} does not exist", file=sys.stderr)
        sys.exit(1)
    return root.resolve()


def resolve_excludes(root_path: Path, excludes: list[str]) -> list[Path]:
    """Convert user provided excludes to resolved Paths."""
    return [(root_path / Path(exclude_path)).resolve() for exclude_path in excludes]


def is_excluded(path: Path, exclude_paths: list[Path]) -> bool:
    """Return True when the given path is within one of the excluded paths."""
    for exclude_path in exclude_paths:
        try:
            path.resolve().relative_to(exclude_path)
        except ValueError:
            continue
        return True
    return False


def gather_python_files(root_path: Path, exclude_paths: list[Path]) -> list[Path]:
    """Return all python files under root that are not excluded."""
    python_files = [
        path for path in root_path.rglob("*.py") if not is_excluded(path, exclude_paths)
    ]
    if not python_files:
        print(f"No Python files found in {root_path}", file=sys.stderr)
        sys.exit(1)
    return python_files


def report_violations(
    violations: list[ComplexityViolation], max_cyclomatic: int, max_cognitive: int
) -> None:
    """Print a summary of violations and exit with appropriate status."""
    if not violations:
        print(
            f"✓ All functions meet complexity limits "
            f"(cyclomatic ≤{max_cyclomatic}, cognitive ≤{max_cognitive})"
        )
        sys.exit(0)

    print(
        f"Complexity violations detected (cyclomatic ≤{max_cyclomatic}, "
        f"cognitive ≤{max_cognitive}):"
    )
    print()

    by_file: dict[str, list[ComplexityViolation]] = {}
    for violation in violations:
        by_file.setdefault(violation.file_path, []).append(violation)

    for file_path in sorted(by_file.keys()):
        file_violations = by_file[file_path]
        print(f"{file_path}:")
        for violation in sorted(file_violations, key=lambda x: x.line_number):
            print(
                f"  - Line {violation.line_number}: {violation.function_name} "
                f"(cyclomatic={violation.cyclomatic}, cognitive={violation.cognitive})"
            )
        print()

    print(f"Total: {len(violations)} function(s) exceed complexity limits")
    sys.exit(1)


def main():
    """Main entry point for complexity guard."""
    args = build_parser().parse_args()
    root_path = resolve_root(args.root)
    exclude_paths = resolve_excludes(root_path, args.exclude)
    python_files = gather_python_files(root_path, exclude_paths)

    all_violations = []
    for file_path in python_files:
        violations = check_file_complexity(
            file_path, args.max_cyclomatic, args.max_cognitive
        )
        all_violations.extend(violations)

    report_violations(all_violations, args.max_cyclomatic, args.max_cognitive)


if __name__ == "__main__":
    main()
