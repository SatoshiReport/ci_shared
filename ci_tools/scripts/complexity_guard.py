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
        def __init__(self):
            self.complexity = 0
            self.nesting_level = 0

        def visit_If(self, node):
            self.complexity += 1 + self.nesting_level
            self.nesting_level += 1
            self.generic_visit(node)
            self.nesting_level -= 1

        def visit_While(self, node):
            self.complexity += 1 + self.nesting_level
            self.nesting_level += 1
            self.generic_visit(node)
            self.nesting_level -= 1

        def visit_For(self, node):
            self.complexity += 1 + self.nesting_level
            self.nesting_level += 1
            self.generic_visit(node)
            self.nesting_level -= 1

        def visit_ExceptHandler(self, node):
            self.complexity += 1 + self.nesting_level
            self.nesting_level += 1
            self.generic_visit(node)
            self.nesting_level -= 1

        def visit_BoolOp(self, node):
            # Each additional condition in a boolean expression adds complexity
            if isinstance(node.op, (ast.And, ast.Or)):
                self.complexity += len(node.values) - 1
            self.generic_visit(node)

        def visit_Lambda(self, node):
            # Don't count nested lambdas - they're separate cognitive units
            pass

    visitor = CognitiveComplexityVisitor()
    visitor.visit(node)
    return visitor.complexity


def check_file_complexity(
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


def main():
    """Main entry point for complexity guard."""
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

    args = parser.parse_args()

    if not args.root.exists():
        print(f"Error: Directory {args.root} does not exist", file=sys.stderr)
        sys.exit(1)

    # Find all Python files
    python_files = list(args.root.rglob("*.py"))

    if not python_files:
        print(f"No Python files found in {args.root}", file=sys.stderr)
        sys.exit(1)

    # Check each file
    all_violations = []
    for file_path in python_files:
        violations = check_file_complexity(
            file_path, args.max_cyclomatic, args.max_cognitive
        )
        all_violations.extend(violations)

    # Report results
    if all_violations:
        print(
            f"Complexity violations detected (cyclomatic ≤{args.max_cyclomatic}, "
            f"cognitive ≤{args.max_cognitive}):"
        )
        print()

        # Group by file
        by_file = {}
        for v in all_violations:
            if v.file_path not in by_file:
                by_file[v.file_path] = []
            by_file[v.file_path].append(v)

        for file_path in sorted(by_file.keys()):
            violations = by_file[file_path]
            print(f"{file_path}:")
            for v in sorted(violations, key=lambda x: x.line_number):
                print(
                    f"  - Line {v.line_number}: {v.function_name} "
                    f"(cyclomatic={v.cyclomatic}, cognitive={v.cognitive})"
                )
            print()

        print(f"Total: {len(all_violations)} function(s) exceed complexity limits")
        sys.exit(1)
    else:
        print(
            f"✓ All functions meet complexity limits "
            f"(cyclomatic ≤{args.max_cyclomatic}, cognitive ≤{args.max_cognitive})"
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
