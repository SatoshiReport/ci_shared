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
from typing import Iterable, Iterator, List, Sequence, Tuple

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
    return bool(stripped) and stripped.upper() == stripped and any(ch.isalpha() for ch in stripped)



def is_numeric_constant(node: ast.AST | None) -> bool:
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



def contains_literal_dataset(node: ast.AST) -> bool:
    if isinstance(node, ast.Dict):
        return any(contains_literal_dataset(value) for value in node.values)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for elt in node.elts:  # type: ignore[attr-defined]
            if isinstance(elt, ast.Constant):
                if isinstance(elt.value, (int, float, str)):
                    return True
            elif isinstance(elt, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
                if contains_literal_dataset(elt):
                    return True
        return False
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (int, float, str))
    return False


def collect_sensitive_assignments() -> List[Violation]:
    violations: List[Violation] = []
    for path in iter_python_files(SCAN_DIRECTORIES):
        tree = parse_ast(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                target_names = []
                for target in node.targets:
                    target_names.extend(extract_target_names(target))
                if not target_names:
                    continue
                lower_names = [name.lower() for name in target_names]
                if not any(
                    token in candidate
                    for candidate in lower_names
                    for token in SENSITIVE_NAME_TOKENS
                ):
                    continue
                if _should_flag_assignment(target_names, node.value):
                    violations.append(
                        Violation(
                            path=path,
                            lineno=node.lineno,
                            message=f"literal assignment {literal_value_repr(node.value)} for {', '.join(sorted(target_names))}",
                        )
                    )
            if isinstance(node, ast.AnnAssign):
                target_names = list(extract_target_names(node.target))
                lower_names = [name.lower() for name in target_names]
                if not any(
                    token in candidate
                    for candidate in lower_names
                    for token in SENSITIVE_NAME_TOKENS
                ):
                    continue
                if _should_flag_assignment(target_names, node.value):
                    violations.append(
                        Violation(
                            path=path,
                            lineno=node.lineno,
                            message=f"annotated literal assignment {literal_value_repr(node.value)} for {', '.join(sorted(target_names))}",
                        )
                    )
    return violations


def collect_dataframe_literals() -> List[Violation]:
    violations: List[Violation] = []
    for path in iter_python_files(SCAN_DIRECTORIES):
        tree = parse_ast(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                qualname = get_call_qualname(node.func)
                if not qualname or qualname not in DATAFRAME_CALLS:
                    continue
                if _allowlisted(qualname, "dataframe"):
                    continue
                if any(
                    contains_literal_dataset(arg)
                    for arg in list(node.args) + [kw.value for kw in node.keywords]
                ):
                    violations.append(
                        Violation(
                            path=path,
                            lineno=node.lineno,
                            message=f"literal dataset passed to {qualname}",
                        )
                    )
    return violations


def collect_numeric_comparisons() -> List[Violation]:
    violations: List[Violation] = []
    for path in iter_python_files(SCAN_DIRECTORIES):
        tree = parse_ast(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                comparator_literals = [
                    comp
                    for comp in node.comparators
                    if is_numeric_constant(comp) and comp.value not in ALLOWED_NUMERIC_LITERALS  # type: ignore[attr-defined]
                ]
                if not comparator_literals:
                    continue
                left_names = []
                for part in (node.left,):
                    if isinstance(part, ast.Name):
                        left_names.append(part.id)
                if not left_names:
                    continue
                lower_names = [name.lower() for name in left_names]
                if not any(
                    token in candidate
                    for candidate in lower_names
                    for token in SENSITIVE_NAME_TOKENS
                ):
                    continue
                if not _should_flag_comparison(left_names):
                    continue
                violations.append(
                    Violation(
                        path=path,
                        lineno=node.lineno,
                        message="comparison against literal "
                        + ", ".join(
                            literal_value_repr(comp) for comp in comparator_literals
                        )
                        + f" for {', '.join(sorted(left_names))}",
                    )
                )
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
