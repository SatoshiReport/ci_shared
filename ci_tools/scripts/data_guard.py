#!/usr/bin/env python3
"""
Guard against hard-coded thresholds, synthetic datasets, and literal fallbacks.
"""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, TypeGuard

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRECTORIES: Sequence[Path] = (ROOT / "src", ROOT / "tests")
ALLOWLIST_PATH = ROOT / "config" / "data_guard_allowlist.json"

SENSITIVE_NAME_TOKENS: Tuple[str, ...] = (
    "threshold",
    "limit",
    "timeout",
    "default",
    "max",
    "min",
    "retry",
    "window",
    "size",
    "count",
)
ALLOWED_NUMERIC_LITERALS = {0, 1, -1}
DATAFRAME_CALLS = {
    "pandas.DataFrame",
    "pd.DataFrame",
    "DataFrame",
    "numpy.array",
    "np.array",
    "numpy.asarray",
    "np.asarray",
}


# DataGuard script uses heuristics; prefer false positives to silent drift.


class DataGuardAllowlistError(RuntimeError):
    """Raised when the allowlist payload cannot be loaded."""

    default_message = "Unable to load data guard allowlist"

    def __init__(self, *, detail: str) -> None:
        super().__init__(f"{self.default_message}: {detail}")


def _load_allowlist() -> Dict[str, set[str]]:
    if not ALLOWLIST_PATH.exists():
        return {"assignments": set(), "comparisons": set(), "dataframe": set()}
    try:
        payload = json.loads(ALLOWLIST_PATH.read_text())
    except json.JSONDecodeError as exc:
        raise DataGuardAllowlistError(
            detail=f"JSON parse error at {ALLOWLIST_PATH}: {exc}"
        ) from exc

    def _coerce_group(key: str) -> set[str]:
        values = payload.get(key, [])
        return {str(item) for item in values}

    return {
        "assignments": _coerce_group("assignments"),
        "comparisons": _coerce_group("comparisons"),
        "dataframe": _coerce_group("dataframe"),
    }


ALLOWLIST = _load_allowlist()


def _allowlisted(name: str, category: str) -> bool:
    group = ALLOWLIST.get(category, set())
    return name in group


class DataGuardViolation(Exception):
    """Raised when the data guard detects a violation."""


@dataclass(frozen=True)
class Violation:
    path: Path
    lineno: int
    message: str


def iter_python_files(bases: Sequence[Path]) -> Iterator[Path]:
    for base in bases:
        if not base.exists():
            continue
        yield from base.rglob("*.py")


def normalize_path(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def parse_ast(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text())
    except Exception:
        return None


def extract_target_names(target: ast.AST) -> Iterable[str]:
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, ast.Tuple):
        for elt in target.elts:
            yield from extract_target_names(elt)
    elif isinstance(target, ast.Attribute):
        yield target.attr


def _is_all_caps_identifier(name: str) -> bool:
    stripped = name.strip()
    return (
        bool(stripped)
        and stripped.upper() == stripped
        and any(ch.isalpha() for ch in stripped)
    )


def is_numeric_constant(node: ast.AST | None) -> TypeGuard[ast.Constant]:
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float))


def literal_value_repr(node: ast.AST | None) -> str:
    if isinstance(node, ast.Constant):
        return repr(node.value)
    return ast.dump(node) if node is not None else "None"


def _should_flag_assignment(target_names: Iterable[str], value: ast.AST | None) -> bool:
    names = [name for name in target_names if name]
    if not names:
        return False
    if all(_is_all_caps_identifier(name) for name in names):
        return False
    if any(_allowlisted(name, "assignments") for name in names):
        return False
    if not (value and is_numeric_constant(value)):
        return False
    return value.value not in ALLOWED_NUMERIC_LITERALS


def _should_flag_comparison(names: Iterable[str]) -> bool:
    identifiers = [name for name in names if name]
    if not identifiers:
        return False
    if all(_is_all_caps_identifier(name) for name in identifiers):
        return False
    return not any(_allowlisted(name, "comparisons") for name in identifiers)


def _sequence_element_has_literal(elt: ast.AST) -> bool:
    if isinstance(elt, ast.Constant):
        return isinstance(elt.value, (int, float, str))
    if isinstance(elt, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return contains_literal_dataset(elt)
    return False


def contains_literal_dataset(node: ast.AST) -> bool:
    if isinstance(node, ast.Dict):
        return any(contains_literal_dataset(value) for value in node.values)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return any(_sequence_element_has_literal(elt) for elt in node.elts)
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str))


def _flatten_assignment_targets(targets: Iterable[ast.AST]) -> list[str]:
    names: list[str] = []
    for target in targets:
        names.extend(extract_target_names(target))
    return names


def _contains_sensitive_token(names: Iterable[str]) -> bool:
    lowered = [name.lower() for name in names]
    return any(
        token in candidate for candidate in lowered for token in SENSITIVE_NAME_TOKENS
    )


def _build_assignment_violation(
    path: Path,
    *,
    target_names: list[str],
    value: ast.AST | None,
    lineno: int,
    prefix: str,
) -> Optional[Violation]:
    if not target_names or not _contains_sensitive_token(target_names):
        return None
    if not _should_flag_assignment(target_names, value):
        return None
    message = (
        f"{prefix} {literal_value_repr(value)} for {', '.join(sorted(target_names))}"
    )
    return Violation(path=path, lineno=lineno, message=message)


def _assignment_violation_from_node(path: Path, node: ast.AST) -> Optional[Violation]:
    if isinstance(node, ast.Assign):
        names = _flatten_assignment_targets(node.targets)
        return _build_assignment_violation(
            path,
            target_names=names,
            value=node.value,
            lineno=node.lineno,
            prefix="literal assignment",
        )
    if isinstance(node, ast.AnnAssign):
        names = list(extract_target_names(node.target))
        return _build_assignment_violation(
            path,
            target_names=names,
            value=node.value,
            lineno=node.lineno,
            prefix="annotated literal assignment",
        )
    return None


def _iter_sensitive_assignment_violations(
    path: Path, tree: ast.AST
) -> Iterator[Violation]:
    for node in ast.walk(tree):
        violation = _assignment_violation_from_node(path, node)
        if violation:
            yield violation


def collect_sensitive_assignments() -> List[Violation]:
    violations: List[Violation] = []
    for path in iter_python_files(SCAN_DIRECTORIES):
        tree = parse_ast(path)
        if tree is None:
            continue
        violations.extend(_iter_sensitive_assignment_violations(path, tree))
    return violations


def _call_contains_literal_arguments(node: ast.Call) -> bool:
    arguments = list(node.args) + [kw.value for kw in node.keywords]
    return any(contains_literal_dataset(arg) for arg in arguments)


def _iter_dataframe_literal_violations(
    path: Path, tree: ast.AST
) -> Iterator[Violation]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        qualname = get_call_qualname(node.func)
        if not qualname or qualname not in DATAFRAME_CALLS:
            continue
        if _allowlisted(qualname, "dataframe"):
            continue
        if _call_contains_literal_arguments(node):
            yield Violation(
                path=path,
                lineno=node.lineno,
                message=f"literal dataset passed to {qualname}",
            )


def collect_dataframe_literals() -> List[Violation]:
    violations: List[Violation] = []
    for path in iter_python_files(SCAN_DIRECTORIES):
        tree = parse_ast(path)
        if tree is None:
            continue
        violations.extend(_iter_dataframe_literal_violations(path, tree))
    return violations


def _literal_comparators(node: ast.Compare) -> list[ast.Constant]:
    return [
        comp
        for comp in node.comparators
        if is_numeric_constant(comp) and comp.value not in ALLOWED_NUMERIC_LITERALS
    ]


def _comparison_targets(node: ast.Compare) -> list[str]:
    if isinstance(node.left, ast.Name):
        return [node.left.id]
    return []


def _format_comparison_message(
    comparator_literals: list[ast.Constant],
    left_names: list[str],
) -> str:
    literal_repr = ", ".join(literal_value_repr(comp) for comp in comparator_literals)
    return (
        "comparison against literal "
        + literal_repr
        + f" for {', '.join(sorted(left_names))}"
    )


def _iter_numeric_comparison_violations(
    path: Path, tree: ast.AST
) -> Iterator[Violation]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        comparator_literals = _literal_comparators(node)
        if not comparator_literals:
            continue
        left_names = _comparison_targets(node)
        if not left_names or not _contains_sensitive_token(left_names):
            continue
        if not _should_flag_comparison(left_names):
            continue
        yield Violation(
            path=path,
            lineno=node.lineno,
            message=_format_comparison_message(comparator_literals, left_names),
        )


def collect_numeric_comparisons() -> List[Violation]:
    violations: List[Violation] = []
    for path in iter_python_files(SCAN_DIRECTORIES):
        tree = parse_ast(path)
        if tree is None:
            continue
        violations.extend(_iter_numeric_comparison_violations(path, tree))
    return violations


def get_call_qualname(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = get_call_qualname(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def collect_all_violations() -> List[Violation]:
    violations: List[Violation] = []
    violations.extend(collect_sensitive_assignments())
    violations.extend(collect_dataframe_literals())
    violations.extend(collect_numeric_comparisons())
    return violations


def main() -> int:
    violations = sorted(
        collect_all_violations(),
        key=lambda item: (normalize_path(item.path), item.lineno, item.message),
    )
    if violations:
        details = "\n".join(
            f"{normalize_path(v.path)}:{v.lineno} -> {v.message}" for v in violations
        )
        raise DataGuardViolation("Data integrity violations detected:\n" + details)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DataGuardViolation as err:
        print(err, file=sys.stderr)
        sys.exit(1)
